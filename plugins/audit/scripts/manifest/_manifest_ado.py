#!/usr/bin/env python3
"""
`meta.ado` - the Azure DevOps connector's config, checked without a network.

Split out of `_manifest_rules.py`. The connector config is the largest single
subject that file held (218 lines against a 1,406-line whole) and the only one
with a second caller: the panel's `write_ado` (PUT /api/ado) validates a
candidate save through `check_ado_meta` before writing it, so the CLI and the
panel cannot disagree about what a valid connector config is. ONE front door,
and it is this module's whole public surface.

The philosophy is the file's standing one, restated because this is where most
of it is exercised: wrong TYPES are findings (a config that would be misread),
unknown KEYS are did-you-mean warnings. `statemap` configuring nothing is
exactly the silence worth naming, and a typo'd `stateMap` status key silently
never fires - the area-tag argument again.

`identityMap` is advisory in USE (nothing gates or assigns on it) and
structural in SHAPE, which is not a contradiction: a malformed map is a defect
like any other wrong type here, while a duplicate target is only a warning
because one person can legitimately hold two ledger identities.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_ado.py` - see
`plugins/audit/tests/_harness.py`.
"""
import os
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

import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)
import _ado_conventions as _conv  # noqa: E402  (what an item must look like to belong)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_manifest_rules.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
STATUS = _vocab.STATUS
BUG_STATUS = _vocab.BUG_STATUS
KNOWN_ADO = _vocab.KNOWN_ADO
_unknown_keys = _vocab._unknown_keys


# --- identityMap -----------------------------------------------------------------
def _check_identity_map(meta, findings, warnings):
    """`meta.ado.identityMap` (v0.38) -- the advisory ledger -> ADO identity map.

    Shape only: an object whose KEYS are ledger identities (the form
    usage.authorMode records authors and area.owner is written in) and whose
    VALUES are ADO identities (email/UPN). The USE is advisory -- /audit:sync
    proposes assignments on push and reverse-maps reportedBy on pull, and
    nothing gates, refuses or assigns on the map by itself -- but a malformed
    map is a structural defect like any other wrong type in this file (the
    ar2 rule: shape is not informational). Deliberately NO email-shape
    policing: an ADO identity is whatever the org's directory says it is,
    and this validator is an offline shape-checker.

    A DUPLICATE VALUE is a WARNING, never a finding: two ledger identities
    mapping to one ADO account is usually a paste error, but one person can
    legitimately hold two ledger identities (usage.authorMode changed
    mid-project, or commits under two git emails). Values are compared
    case-insensitively because ADO identities are."""
    ado = meta.get("ado")
    if not isinstance(ado, dict) or "identityMap" not in ado:
        return
    imap = ado.get("identityMap")
    if imap is None:
        return
    if not isinstance(imap, dict):
        findings.append("meta.ado.identityMap: must be an object mapping "
                        "ledger identity -> ADO identity (email/UPN), got %s"
                        % type(imap).__name__)
        return
    targets = {}   # lowercased ADO identity -> [ledger key, ...] in map order
    shown = {}     # lowercased ADO identity -> first spelling seen
    for k, v in imap.items():
        if not isinstance(k, str) or not str(k).strip():
            findings.append("meta.ado.identityMap: keys must be non-empty "
                            "ledger identity strings (the form usage."
                            "authorMode records), got %r" % (k,))
        if not isinstance(v, str) or not v.strip():
            findings.append("meta.ado.identityMap[%r]: value must be a "
                            "non-empty ADO identity string (email/UPN), "
                            "got %r" % (k, v))
            continue
        low = v.strip().lower()
        targets.setdefault(low, []).append(k)
        shown.setdefault(low, v.strip())
    for low, keys in targets.items():
        if len(keys) > 1:
            warnings.append(
                "meta.ado.identityMap: %r is the target of %d ledger "
                "identities (%s) -- usually a paste error, though one person "
                "CAN legitimately hold two ledger identities (e.g. "
                "usage.authorMode changed mid-project); /audit:sync pull "
                "maps this ADO identity back to the FIRST key in map order"
                % (shown[low], len(keys),
                   ", ".join(repr(k) for k in keys)))


# --- the connector config --------------------------------------------------------
def check_ado_meta(ado):
    """The full meta.ado connector-config check. Returns (findings, warnings).

    ONE front door on purpose: validate() calls this for the manifest, and the
    panel's write_ado (PUT /api/ado) calls it for a candidate save -- so the
    CLI and the panel cannot disagree about what a valid config is.

    null/absent = connector off, an answer -- silent. The v2 keys follow the
    file's standing philosophy: wrong TYPES are findings (a config that would
    be misread), unknown KEYS are did-you-mean warnings (the typo catcher --
    `statemap` configuring nothing is exactly the silence worth naming). The
    stateMap's status keys get the same warning treatment: a typo'd status
    silently never fires, which is the area-tag argument all over again."""
    f, w = [], []
    if ado is None:
        return f, w
    if not isinstance(ado, dict):
        f.append("meta: ado must be an object or null, got %s"
                 % type(ado).__name__)
        return f, w
    _unknown_keys(ado, KNOWN_ADO, "meta.ado", w)
    _check_identity_map({"ado": ado}, f, w)

    for key in ("organization", "project"):
        val = ado.get(key)
        if key in ado and (not isinstance(val, str) or not val.strip()):
            f.append("meta.ado.%s: must be a non-empty string, got %r"
                     % (key, val))
    for key in ("areaPath", "iterationPath"):
        val = ado.get(key)
        if key in ado and val is not None and not isinstance(val, str):
            f.append("meta.ado.%s: must be a string or null, got %s"
                     % (key, type(val).__name__))
    for key in ("enabled", "echo", "phaseWorkItems"):
        val = ado.get(key)
        if key in ado and not isinstance(val, bool):
            f.append("meta.ado.%s: must be true or false, got %r" % (key, val))
    tag = ado.get("tag")
    if "tag" in ado and tag is not None and (
            not isinstance(tag, str) or not tag.strip()):
        f.append("meta.ado.tag: must be a non-empty string or null (null = "
                 "no provenance tag; absent = 'audit-plugin'), got %r" % (tag,))

    types = ado.get("types")
    if "types" in ado and types is not None:
        if not isinstance(types, dict):
            f.append("meta.ado.types: must be an object, got %s"
                     % type(types).__name__)
        else:
            for k, v in types.items():
                if k == "pbi" and v is None:
                    continue  # null pbi = auto-detect at first phase push
                if not isinstance(v, str) or not v.strip():
                    f.append("meta.ado.types: every value must be a work-item "
                             "type name (non-empty string%s), got %s=%r"
                             % ("; pbi may be null = auto-detect", k, v))

    sm = ado.get("stateMap")
    if "stateMap" in ado and sm is not None:
        if not isinstance(sm, dict):
            f.append("meta.ado.stateMap: must be an object {task, bug, phase} "
                     "or null, got %s" % type(sm).__name__)
        else:
            # F1 (live gate): phase work items have their OWN state vocabulary
            # in ADO (a Scrum PBI knows no "In Progress"), so the map carries a
            # third block, keyed by the same status names phases use.
            vocab = {"task": STATUS, "bug": BUG_STATUS, "phase": STATUS}
            _unknown_keys(sm, set(vocab), "meta.ado.stateMap", w)
            for kind, statuses in vocab.items():
                block = sm.get(kind)
                if kind not in sm or block is None:
                    continue
                if not isinstance(block, dict):
                    f.append("meta.ado.stateMap.%s: must be an object of "
                             "status -> ADO state, got %s"
                             % (kind, type(block).__name__))
                    continue
                _unknown_keys(block, set(statuses),
                              "meta.ado.stateMap.%s" % kind, w)
                for st, val in block.items():
                    if st not in statuses or val is None:
                        continue  # unknown key already warned; null = never move
                    if not isinstance(val, str) or not val.strip():
                        f.append("meta.ado.stateMap.%s.%s: must be an ADO "
                                 "state name or null (null = never move this "
                                 "transition), got %r" % (kind, st, val))

    oc = ado.get("onComplete")
    if "onComplete" in ado and oc is not None:
        if not isinstance(oc, dict):
            f.append("meta.ado.onComplete: must be an object or null, got %s"
                     % type(oc).__name__)
        else:
            _unknown_keys(oc, {"remainingWork"}, "meta.ado.onComplete", w)
            rw = oc.get("remainingWork")
            if "remainingWork" in oc and rw is not None:
                if (isinstance(rw, bool) or not isinstance(rw, (int, float))
                        or rw < 0):
                    f.append("meta.ado.onComplete.remainingWork: must be a "
                             "number >= 0 or null (null = never touch the "
                             "field), got %r" % (rw,))

    cm = ado.get("comments")
    if "comments" in ado and cm is not None:
        if not isinstance(cm, dict):
            f.append("meta.ado.comments: must be an object or null, got %s"
                     % type(cm).__name__)
        else:
            _unknown_keys(cm, {"onBlocked", "onComplete"},
                          "meta.ado.comments", w)
            for key in ("onBlocked", "onComplete"):
                val = cm.get(key)
                if key in cm and not isinstance(val, bool):
                    f.append("meta.ado.comments.%s: must be true or false, "
                             "got %r" % (key, val))

    sp = ado.get("sprint")
    if "sprint" in ado and sp is not None:
        if not isinstance(sp, dict):
            f.append("meta.ado.sprint: must be an object {team, mode} or "
                     "null, got %s" % type(sp).__name__)
        else:
            _unknown_keys(sp, {"team", "mode"}, "meta.ado.sprint", w)
            team = sp.get("team")
            if not isinstance(team, str) or not team.strip():
                f.append("meta.ado.sprint: requires a non-empty 'team' -- "
                         "the team whose iteration calendar defines "
                         "'current', got %r" % (team,))
            mode = sp.get("mode")
            if "mode" in sp and mode != "current":
                f.append("meta.ado.sprint.mode: must be 'current' (the only "
                         "mode today; static paths belong in "
                         "meta.ado.iterationPath), got %r" % (mode,))

    pl = ado.get("pull")
    if "pull" in ado and pl is not None:
        if not isinstance(pl, dict):
            f.append("meta.ado.pull: must be an object {areaPath, tags} or "
                     "null, got %s" % type(pl).__name__)
        else:
            _unknown_keys(pl, {"areaPath", "tags"}, "meta.ado.pull", w)
            ap = pl.get("areaPath")
            if "areaPath" in pl and ap is not None and not isinstance(ap, str):
                f.append("meta.ado.pull.areaPath: must be a string or null, "
                         "got %s" % type(ap).__name__)
            tags = pl.get("tags")
            if "tags" in pl:
                if not isinstance(tags, list):
                    f.append("meta.ado.pull.tags: must be an array of tags, "
                             "got %s" % type(tags).__name__)
                else:
                    bad = [t for t in tags
                           if not isinstance(t, str) or not t.strip()]
                    if bad:
                        f.append("meta.ado.pull.tags: every tag must be a "
                                 "non-empty string (%d bad: %r)"
                                 % (len(bad), bad[:3]))

    # `parentWorkItem`: the EXISTING item audit work hangs under. Without it the
    # connector always builds its own branch, which on a board that already has a
    # Feature/Story backlog puts audit work BESIDE their planning instead of
    # inside it - correct, and invisible to everyone who plans from that board.
    # An id, so an int: a config carrying "103205" as a string is a typo worth
    # naming rather than something to coerce, because the coercion would hide it.
    if "parentWorkItem" in ado:
        pwi = ado.get("parentWorkItem")
        if pwi is not None and (isinstance(pwi, bool) or not isinstance(pwi, int)):
            f.append("meta.ado.parentWorkItem must be a work item id (integer) "
                     "or null, got %s" % type(pwi).__name__)
        elif isinstance(pwi, int) and not isinstance(pwi, bool) and pwi <= 0:
            f.append("meta.ado.parentWorkItem must be a positive work item id, "
                     "got %r" % (pwi,))

    # `conventions` is graded by `_ado_conventions`, not here. Same reason this
    # module reads `_manifest_vocab`'s words rather than its own: the panel's
    # PUT /api/ado comes through this same front door, and two implementations
    # of "is this block valid" are two answers the first time one learns a key.
    cf, cw = _conv.check_conventions_config(ado.get("conventions"))
    f.extend(cf)
    w.extend(cw)
    return f, w

# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_manifest_ado.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_ado.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
