#!/usr/bin/env python3
"""
What a manifest id looks like, and which one to mint next - so two branches cannot
both mint the same one.

Every allocator here is max+1, and max+1 is taken on ONE branch: two branches from
one base both mint `BUG-12`, and the record merge can only report that, because
which side keeps the id depends on which was published first and the merge cannot
know. So an id minted anywhere but the development branch carries a suffix drawn
from the branch name - `BUG-12-k7m`, `P61-k7m`, `P60.6-k7m` - and two branches
cannot produce the same one. On the development branch (and on any branch a phase
names as its parent) ids stay exactly what they were, so a solo plan never sees
the suffix at all.

THE NUMBER STAYS THE NUMBER. The suffix is ignored when the next number is taken,
so ids keep reading in the order they were made and the development branch, after
a merge, continues from the highest number either side reached.

THE ALPHABET IS `[0-9a-z]`. A phase id becomes a lock name (`_locks.valid_name`
takes `[A-Za-z0-9._-]`), a shard file name and a lower-cased branch component, so
the suffix is lower case and survives all three unchanged.

WHAT IT DOES NOT PREVENT: two clones minting on the development branch itself.
That collision still reaches the merge, which names it, and
`merge-manifest.py resolve` renumbers the side the operator picks.
"""
import hashlib
import os
import re
import subprocess
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

import _branch  # noqa: E402  (parent_branch: the one answer to "which branch is the trunk")
import _manifest_vocab  # noqa: E402  (ID_SUFFIX: the suffix's one spelling)
import _manifest_io as _mio  # noqa: E402  (moved_from_ids: the ids a moved task held)


ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
SUFFIX_LEN = 3


# --- the suffix -----------------------------------------------------------------
def trunk_branches(manifest):
    """Branches that mint unsuffixed ids: the development branch, and every branch
    a phase forks from. Read through `_branch.parent_branch`, so this and the
    branch a phase is merged back into cannot disagree about what the trunk is."""
    meta = (manifest or {}).get("meta") or {}
    out = set([_branch.parent_branch(meta, None)["branch"]])
    for phase in (manifest or {}).get("phases") or []:
        if isinstance(phase, dict):
            out.add(_branch.parent_branch(meta, phase)["branch"])
    return out


def branch_suffix(branch, manifest, origin_head=None, branches=None):
    """The suffix this branch mints, or None on a trunk branch or with no branch.

    `origin_head` is the branch the remote's HEAD names: a clone of a repository
    whose trunk is `master`, with no `developmentBranch` configured, would
    otherwise suffix every id minted on its own trunk. `branches` is every branch
    name the repository has, local or remote-tracking; when none of them is a
    trunk there is nothing to tell a side branch from, and minting a suffix there
    would only rename a solo plan's ids."""
    trunks = trunk_branches(manifest)
    if origin_head:
        trunks.add(origin_head)
    if not branch or branch in trunks:
        return None
    if branches is not None and not (trunks & set(branches)):
        return None
    n = int(hashlib.sha1(branch.encode("utf-8")).hexdigest(), 16)
    chars = []
    for _i in range(SUFFIX_LEN):
        n, r = divmod(n, len(ALPHABET))
        chars.append(ALPHABET[r])
    return "".join(chars)


def current_branch(cwd):
    """The checked-out branch, or None when detached, unborn-and-unnamed, or not in
    a repository. `symbolic-ref` rather than `rev-parse --abbrev-ref`, because the
    second fails on a branch with no commit yet and that is where a first plan is
    written."""
    try:
        r = subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    out = r.stdout.decode("utf-8", "replace").strip()
    return out if r.returncode == 0 and out else None


def _git_lines(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return [ln.strip() for ln in r.stdout.decode("utf-8", "replace").splitlines()
            if ln.strip()]


def suffix_here(cwd, manifest):
    """The suffix an id minted in the repository at `cwd` carries right now - the
    one call every allocator makes, so none of them reads the branch its own way."""
    branch = current_branch(cwd)
    if not branch:
        return None
    head = _git_lines(cwd, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    origin_head = head[0].split("/", 1)[1] if head and "/" in head[0] else None
    # A local name may itself hold a slash (`feature/x`); only a remote-tracking
    # name loses its first component (`upstream/main` -> `main`).
    local = _git_lines(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads") or []
    remote = _git_lines(cwd, "for-each-ref", "--format=%(refname:short)", "refs/remotes") or []
    branches = set(local) | set(n.split("/", 1)[1] for n in remote if "/" in n)
    return branch_suffix(branch, manifest, origin_head=origin_head, branches=branches)


# --- numbers --------------------------------------------------------------------
def number(ident, prefix):
    """The number in `<prefix><n>[-suffix]`, or None when `ident` is not that shape."""
    m = re.match(r"\A%s(\d+)%s\Z" % (re.escape(prefix), _manifest_vocab.ID_SUFFIX),
                 "%s" % (ident,))
    return int(m.group(1)) if m else None


def _mint(prefix, taken, suffix):
    nums = [n for n in (number(t, prefix) for t in taken) if n is not None]
    return "%s%d%s" % (prefix, (max(nums) if nums else 0) + 1,
                       ("-" + suffix) if suffix else "")


def next_bug_id(manifest, suffix):
    """`BUG-<max+1>[-suffix]` over every bug, suffixed or not."""
    return _mint("BUG-", [b.get("id") for b in (manifest or {}).get("bugs") or []
                          if isinstance(b, dict)], suffix)


def next_prop_id(manifest, suffix):
    """`PROP-<max+1>[-suffix]` over every proposal. A proposal is what a phase
    branch writes INSTEAD of a phase, so it is exactly the record two branches
    both mint; a legacy free-form id carries no number and is passed over."""
    return _mint("PROP-", [p.get("id") for p in (manifest or {}).get("proposals") or []
                           if isinstance(p, dict)], suffix)


def next_task_id(manifest, phase_id, suffix, extra_ids=()):
    """`<phaseId>.<max+1>[-suffix]`. A phase that already carries this branch's
    suffix was minted here, so its tasks do not repeat it. `extra_ids` are ids
    reserved elsewhere (parked proposals) that must not be reused.

    EVERY ID A LIVE TASK WAS MOVED FROM IS TAKEN TOO, down the whole `movedFrom`
    chain. `move` takes an id out of its phase, and minting it again would hand
    the ledger, evidence and journal rows written under it to an unrelated task,
    and bind another branch's `blockedBy` on it to the wrong one after a merge."""
    prefix = "%s." % (phase_id,)
    if suffix and str(phase_id).endswith("-" + suffix):
        suffix = None
    taken = list(extra_ids)
    for phase in (manifest or {}).get("phases") or []:
        for task in (phase or {}).get("tasks") or []:
            if isinstance(task, dict):
                taken.append(task.get("id"))
                taken.extend(_mio.moved_from_ids(task))
    return _mint(prefix, taken, suffix)



def is_placeholder_phase(phase_id):
    """True for `P<n>-<suffix>`: a phase id a SIDE branch reserved for a parked
    proposal. Phases are minted on the development branch, so this id is never a
    live phase's - `materialize` mints the real `P<n>` in its place."""
    return bool(re.match(r"\AP\d+-[0-9a-z]{%d}\Z" % (SUFFIX_LEN,), "%s" % (phase_id,)))


def next_phase_id(taken, suffix):
    """`P<max+1>[-suffix]` over every taken id reading as `P<n>[-suffix]`."""
    return _mint("P", taken, suffix)
