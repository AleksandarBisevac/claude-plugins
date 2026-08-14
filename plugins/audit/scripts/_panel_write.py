#!/usr/bin/env python3
"""
The panel's WRITE side: everything a `PUT /api/*` actually does, off panel-server.py.

Moved out of panel-server.py (P12.4). Given a project directory this is the whole
path from a request body to bytes on disk and a row in the journal: the lock that
makes a write safe against a running /audit command (`_acquire_write_lock` /
`_release_write_lock`), the change rows that let the panel say what a save WOULD
change and then prove it changed exactly that (`_flat_paths`, `_config_changes`,
`_composition_changes`, `_fmt_change`), the tamper-evident record of it
(`_journal`), and the four writers themselves -- `write_config`,
`apply_composition` (with `_reject_unknown` / `apply_composition_patch` /
`_touched_phase_ids` / `_write_back`), plus the two wholesale-replace endpoints
`write_policy` and `write_areas` that go THROUGH them rather than beside them.

Where this module sits: ABOVE _loader / _manifest_io / _areas / _policy /
_panel_settings / _panel_state, and BELOW panel-server. It must never import
panel-server -- a selftest case below says so. The DAG is
_panel_state -> _panel_write -> panel-server.

panel-server.py keeps a thin module-level alias for every name moved here, so its
PUT/POST routes and the rest of its selftest keep referring to them unchanged.

BOUNDARY DECISIONS -- names this module shares with the read side:

  * `_atomic_write_json`. P12.3 deliberately left it in panel-server for this
    task; it is the one WRITE the read side never makes, so it moved HERE and is
    aliased back. It stays a wrapper rather than being inlined as
    `_mio.atomic_write_json(...)` at each of its call sites: `ensure_ascii=False,
    indent=2` is this panel's byte shape, and spelling it at seven call sites is
    seven places for one of them to drift.

  * `_JOURNAL` / `_journalmod`. The module handle moved to _panel_state in P12.3
    (its `journal_state` reads the same journal this writes). It is reached here
    through that module -- `_JOURNAL` is the SAME dict object, not a copy -- so a
    selftest that swaps a stub module in by mutating it in place is seen by the
    writer, by `journal_state` and by panel-server alike. Two memos would be two
    answers to "is there a journal on this install", and the case pinning the
    identity is below (and its twin is in _panel_state's suite).

  * `read_config` / `_cores` / `_within` / `_config_path` / `_manifest_path` /
    `_read_json` / `_viewer` / `_skills_of` and the lock readers (`_lockmod`,
    `_lock_info`, `_audit_lock_dir`, `_audit_lock_held`) come from _panel_state
    for the same reason: one memo, one answer, one implementation of "where is
    the manifest" on both sides of a save.

  * The allow-lists (`_META_KEYS` / `_PHASE_KEYS` / `_TASK_KEYS`) come from
    _panel_settings, which is where the shape of a setting is decided.

Stdlib only, Python 3.8 compatible.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (meta.areas registry + shared resolution)
import _policy                # noqa: E402  (the capability policy + its resolution)
import _panel_settings        # noqa: E402  (settings-form schema + write allow-lists)
import _panel_state           # noqa: E402  (the read side this write path reads through)

# The write allow-lists: what a composition patch may legally name.
_META_KEYS = _panel_settings._META_KEYS
_PHASE_KEYS = _panel_settings._PHASE_KEYS
_TASK_KEYS = _panel_settings._TASK_KEYS

# The read side, by identity — see the docstring above for why each of these is
# reached rather than reimplemented.
_cores = _panel_state._cores
_within = _panel_state._within
_config_path = _panel_state._config_path
_manifest_path = _panel_state._manifest_path
_read_json = _panel_state._read_json
read_config = _panel_state.read_config
_skills_of = _panel_state._skills_of
_viewer = _panel_state._viewer
_JOURNAL = _panel_state._JOURNAL
_journalmod = _panel_state._journalmod
_audit_lock_dir = _panel_state._audit_lock_dir
_audit_lock_held = _panel_state._audit_lock_held
_lockmod = _panel_state._lockmod
_lock_info = _panel_state._lock_info


def _src_of_this_file():
    """This module's own source -- for the selftests that must assert a server-side
    construct (an import boundary) rather than a rendered string."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


def _atomic_write_json(path, obj):
    """Thin delegation to the plugin's ONE atomic-JSON-write implementation
    (_manifest_io.atomic_write_json) — ensure_ascii=False keeps this module's
    existing byte shape unchanged."""
    _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)


def write_policy(project, body):
    """`PUT /api/policy` — replace the `policy` block wholesale.

    Wholesale for the same reason the registry is: a policy is a set of rules, and
    removing one is as ordinary an edit as adding one.

    Checked HERE before anything is written, so the caller gets
    `policy.skills.default: must be 'allow' or 'deny'` rather than the same fact
    restated across a whole-config validation. The write itself then goes through
    `write_config` — the one config writer — which validates the WHOLE file again,
    takes the lock, writes atomically and journals the change rows. That is also
    what makes the refusal below mechanical rather than a second rule living here:
    a policy denying audit's own components is a validator FINDING, so the write
    path already refuses it, and this check exists to say so in the policy's own
    words before the file is even assembled.
    """
    if not isinstance(body, dict):
        return {"ok": False, "findings": ["body must be a JSON object"]}
    policy = body.get("policy") if "policy" in body else body
    if policy is None:
        policy = {}
    findings, warnings = _policy.validate_policy(policy)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    config = read_config(project)
    updated = dict(config)
    updated["policy"] = policy
    res = write_config(project, updated)
    if res.get("ok"):
        res["warnings"] = list(res.get("warnings") or []) + warnings
    return res


def write_areas(project, body):
    """`PUT /api/areas` — replace `meta.areas` wholesale.

    Wholesale because a registry is a set: dropping an area is as ordinary an edit
    as adding one, and a merge-shaped API gives no way to say "this tag is gone".

    The shape is checked HERE, before anything is written, so the caller gets
    `meta.areas.api.root: must be a non-empty…` instead of the same fact restated
    as a manifest validator finding after a lock has been taken. The write itself
    then goes through `apply_composition`, which is the only writer: it takes the
    lock, re-validates the assembled document, patches the INDEX alone (meta lives
    there — a registry save must not touch a phase shard and manufacture a conflict
    on a branch nobody is on), echoes the change rows and journals them.
    """
    if not isinstance(body, dict):
        return {"ok": False, "findings": ["body must be a JSON object"]}
    # Accept either {"areas": {...}} or the bare registry, since both readings of
    # "PUT the areas" are reasonable and guessing wrong costs a confusing 400.
    areas = body.get("areas") if "areas" in body else body
    if areas is None:
        areas = {}
    findings, warnings = _areas.validate_registry(areas)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    res = apply_composition(project, {"meta": {"areas": areas}})
    if res.get("ok"):
        res["warnings"] = list(res.get("warnings") or []) + warnings
    return res


# --- write locking ---------------------------------------------------------------
def _panel_session():
    """This panel's lock identity. A pid the OS can vouch for is what lets a
    crashed panel's lock be judged dead rather than waited out for an hour."""
    return "panel-%d" % os.getpid()


def _acquire_write_lock(project, config, touched_phases=None):
    """Take the index lock for the duration of a write.

    Returns {"blocked": False, ...} when the caller may proceed, or
    {"blocked": True, "response": <dict to return to the client>}.

    `touched_phases` matters only in the sharded layout: a phase running in
    another worktree owns its own shard, and editing a DIFFERENT phase's shard
    cannot conflict with it. Passing None (single file) means any phase lock
    contends, because there is only one file.
    """
    lockmod = _lockmod()
    mpath = _manifest_path(project, config)
    if lockmod is None:
        # No lock library: fall back to the old check-only behaviour rather than
        # writing unguarded or refusing everything.
        if _audit_lock_held(project, config):
            return {"blocked": True, "response": {
                "ok": False, "locked": True,
                "findings": ["manifest is locked by a running /audit command; "
                             "try again once it finishes"]}}
        return {"blocked": False, "held": False}

    # A phase lock on a shard this write does not touch is not our business: that
    # phase owns its own file, and editing a different one cannot collide with it.
    # An abandoned lock does not block either — that is what `live` is for.
    info = _lock_info(_audit_lock_dir(project, config)) or {}
    blocking = [pid for pid, ph in (info.get("phases") or {}).items()
                if (ph or {}).get("live", True)
                and (touched_phases is None or pid in touched_phases)]
    if blocking:
        host = ((info.get("phases") or {}).get(blocking[0]) or {}).get("hostname")
        return {"blocked": True, "response": {
            "ok": False, "locked": True, "lockedPhases": sorted(blocking),
            "findings": ["phase %s is running elsewhere (%s); it cannot be edited "
                         "until that run finishes"
                         % (", ".join(sorted(blocking)), host or "unknown host")]}}

    git_root = os.path.join(project, (config or {}).get("gitRoot") or ".")
    out = []
    try:
        code = lockmod.main(["acquire", "index", "--project", git_root,
                             "--note", "panel write", "--session", _panel_session(),
                             "--pid", str(os.getpid())], out=out.append)
    except Exception:
        code = None
    if code == 0:
        return {"blocked": False, "held": True, "project": git_root, "mod": lockmod}
    if code == getattr(lockmod, "E_LIVE", 3):
        return {"blocked": True, "response": {
            "ok": False, "locked": True,
            "findings": [" ".join(out).strip()
                         or "the manifest is locked by a running /audit command; "
                            "try again once it finishes"]}}
    if code == getattr(lockmod, "E_STALE", 4):
        # Never taken over silently: a lock whose holder died is a decision for
        # the person who knows what that run was doing.
        return {"blocked": True, "response": {
            "ok": False, "locked": True, "lockStale": True,
            "findings": [(" ".join(out).strip() + " ") if out else "" +
                         "Release it with: audit-lock.py release index --project ."]}}
    # Not a git repo (or the lock library refused for a reason of its own): keep
    # the legacy working-tree lock as the guard rather than writing unguarded.
    legacy = mpath + ".lock"
    try:
        fd = os.open(legacy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        return {"blocked": False, "held": True, "legacy": legacy}
    except FileExistsError:
        return {"blocked": True, "response": {
            "ok": False, "locked": True,
            "findings": ["manifest is locked by a running /audit command; "
                         "try again once it finishes"]}}
    except OSError:
        return {"blocked": False, "held": False}


def _release_write_lock(lock):
    """Give the lock back. Never raises: a write that succeeded must not be
    reported as failed because the release did."""
    if not lock or not lock.get("held"):
        return
    try:
        if lock.get("legacy"):
            os.unlink(lock["legacy"])
            return
        mod = lock.get("mod")
        if mod is not None:
            mod.main(["release", "index", "--project", lock.get("project") or ".",
                      "--session", _panel_session(), "--pid", str(os.getpid())],
                     out=lambda *_a, **_k: None)
    except Exception:
        pass


# --- what a save would change, and the record of it -------------------------------
# One row shape for both writers and for the journal: {target, field, from, to}.
# The panel renders it as "P1.2 · model · sonnet -> opus" before you confirm, the
# server recomputes it from the document on disk and echoes it back as `applied`,
# and the client compares the two. That comparison is the point: it is what turns
# "the save went through" into "the save changed exactly what I was shown", and it
# catches the case a confirm dialog otherwise makes WORSE — a second tab, or an
# /audit run, having moved the manifest under you between render and save.
def _flat_paths(obj, prefix=""):
    """Dotted leaf paths of a JSON object. Lists and empty dicts are leaves.

    A leaf per path rather than per block so `usage.bands.highUSD` reads as one
    change instead of "usage changed" — which is not a sentence anyone can check.
    """
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            if isinstance(v, dict) and v:
                out.update(_flat_paths(v, p))
            else:
                out[p] = v
    return out


def _config_changes(before, after):
    """Rows for a config save: one per dotted leaf path that actually differs."""
    a, b = _flat_paths(before or {}), _flat_paths(after or {})
    rows = []
    for p in sorted(set(a) | set(b)):
        # Presence as well as value: removing a key whose value was null is a real
        # change — deleting the key is how "use the default" is written — and
        # comparing two `.get()` results alone would call that a no-op.
        if (p in a) == (p in b) and a.get(p) == b.get(p):
            continue
        rows.append({"target": "config", "field": p,
                     "from": a.get(p), "to": b.get(p)})
    return rows


def _composition_changes(manifest, patch):
    """Rows for a composition save, computed BEFORE the patch is applied.

    Read off the ASSEMBLED manifest — the same document the panel rendered its form
    from — so the client's list and this one are two readings of one pair of values.

    A field set back to the value it already had is dropped here, and the client
    drops it too. That symmetry is what makes the mismatch check mean something: a
    row on one side only is news, not a difference of opinion about what counts.

    Unknown ids are skipped rather than reported: `apply_composition_patch` refuses
    them a moment later, with the message that names them.
    """
    rows = []
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    for k in _META_KEYS:
        if k in (patch.get("meta") or {}):
            was, now = meta.get(k), patch["meta"][k]
            if was != now:
                rows.append({"target": "meta", "field": k, "from": was, "to": now})
    by_pid = {p.get("id"): p for p in (manifest.get("phases") or [])
              if isinstance(p, dict)}
    for pid, pv in sorted((patch.get("phases") or {}).items()):
        ph = by_pid.get(pid)
        if ph is None or "reviewModel" not in (pv or {}):
            continue
        rev = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        was, now = rev.get("model"), pv["reviewModel"]
        if was != now:
            rows.append({"target": pid, "field": "review model",
                         "from": was, "to": now})
    by_tid = {t.get("id"): t for p in (manifest.get("phases") or [])
              if isinstance(p, dict)
              for t in (p.get("tasks") or []) if isinstance(t, dict)}
    for tid, tv in sorted((patch.get("tasks") or {}).items()):
        t = by_tid.get(tid)
        if t is None:
            continue
        for k in _TASK_KEYS:
            if k in (tv or {}):
                # `skills` through the same normaliser the view uses — see
                # _skills_of for why the raw value would be the wrong `from`.
                was = _skills_of(t) if k == "skills" else t.get(k)
                now = tv[k]
                if was != now:
                    rows.append({"target": tid, "field": k,
                                 "from": was, "to": now})
    return rows


def _heal_phase_status(manifest):
    """Flip 'pending' phases that already hold an in_progress task, in place.

    v0.37 A4: the validator's "task in_progress but its phase is pending"
    warning stays as the backstop for hand edits, but a write THIS code makes
    must not persist an inconsistency it can see -- the phase goes
    in_progress in the SAME write. Returns the change rows
    ({target, field, from, to}) for the phases healed; they are journaled
    with the save and reported to the client apart from `applied`, whose
    contract is "the echo of what the dialog showed" -- and the dialog did
    not show this.
    """
    rows = []
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict) or ph.get("status") != "pending":
            continue
        if any(isinstance(t, dict) and t.get("status") == "in_progress"
               for t in (ph.get("tasks") or [])):
            ph["status"] = "in_progress"
            rows.append({"target": ph.get("id"), "field": "status",
                         "from": "pending", "to": "in_progress"})
    return rows


def _fmt_change(row):
    """One row as the panel prints it, for the journal's one-line summary.

    Every value except a plain string is JSON-spelled, which matters for exactly
    one type and was wrong for it until the journal made it visible: `str(True)` is
    `True`, and the dialog beside it says `true`. Whoever reads this line is
    holding a JSON file, where `True` is not something they can type — the same
    reason the areas validator spells its values in JSON rather than in Python.
    Strings stay bare, because quoting every model name would be noise.

    On a `skills` row, null is not "(unset)": it is the explicit opt-out
    (v0.37 B1), and a journal line that read `skills: [] -> (unset)` would
    record the one deliberate answer as an absence.
    """
    def side(v):
        if v is None:
            return ("null (opted out)" if row.get("field") == "skills"
                    else "(unset)")
        if isinstance(v, str):
            return v
        return json.dumps(v, sort_keys=True)
    return "%s %s: %s -> %s" % (row.get("target"), row.get("field"),
                                side(row.get("from")), side(row.get("to")))


def _journal(project, config, action, target, rows):
    """Append one row to the tamper-evident journal. Response fields, not a bool.

    FAIL-SOFT BY CONTRACT, and the contract is the interesting part: a write that
    SUCCEEDED must never be reported as failed because the journal was absent,
    unwritable or broken. Nothing here can raise into a writer.

    Returns `{"journaled": True}`, or False plus a `journaledWhy` that the panel
    needs in order not to lie in either direction:

      "unavailable" — this install has no journal (the module ships with v0.29,
        this call site ships now). The toast then says nothing about logging at
        all: "not logged" would advertise a feature that is not here and make every
        ordinary save read like a failure.
      "failed"      — the journal exists and would not take the row. That one IS
        worth saying out loud, in the same breath as the save: an unlogged change
        and a broken audit trail are not the same news.

    The changes go into `summary` rather than a field of their own: the journal row
    is a fixed shape ({v, ts, actor, action, target, summary, stateHash, prev,
    hash}) and inventing a key here would be this file deciding a format that file
    owns.

    The module handle is _panel_state's memo, reached by identity: the reader
    (`journal_state`) and this writer must agree about whether there is a journal
    on this install, including when a selftest swaps a stub into it.
    """
    mod = _journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    try:
        ok = bool(mod.append(project, {
            "action": action,
            "target": target,
            "summary": "%d change(s): %s" % (
                len(rows), "; ".join(_fmt_change(r) for r in rows)),
            "actor": {"author": _viewer(project, config).get("author"),
                      "sessionId": _panel_session(), "via": "panel"}}))
    except Exception:
        ok = False
    return {"journaled": True} if ok else {"journaled": False,
                                           "journaledWhy": "failed"}


# --- writes ---------------------------------------------------------------------
def write_config(project, obj):
    """Validate then atomically write .claude/audit.config.json. Returns dict."""
    _, vc, _, _ = _cores()
    if not isinstance(obj, dict):
        return {"ok": False, "findings": ["config must be a JSON object"]}
    findings, warnings = vc.validate_config(obj)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    path = _config_path(project)
    if not _within(project, path):
        return {"ok": False, "findings": ["refused: path escapes project"]}
    current = read_config(project)
    applied = _config_changes(current, obj)
    if not applied:
        # Nothing to write. Not an error and not a lie either: the response says
        # `unchanged`, so the panel can say "no changes" rather than "saved" —
        # and no file is touched, so a save with nothing in it cannot rewrite a
        # config someone else edited in the meantime.
        return {"ok": True, "findings": [], "warnings": warnings, "applied": [],
                "unchanged": True, "journaled": False,
                "journaledWhy": "unchanged",
                "path": os.path.relpath(path, project)}
    # The config decides where the manifest is and which guards run; writing it
    # under a running phase is the same class of surprise as writing the manifest.
    lock = _acquire_write_lock(project, current, None)
    if lock.get("blocked"):
        return lock["response"]
    try:
        _atomic_write_json(path, obj)
    finally:
        _release_write_lock(lock)
    out = {"ok": True, "findings": [], "warnings": warnings, "applied": applied,
           "path": os.path.relpath(path, project)}
    # `current`, not the config just written: the actor is resolved under the mode
    # that was in force when they made the change, not one this same save may have
    # altered.
    out.update(_journal(project, current, "config.write", out["path"], applied))
    return out


def _reject_unknown(patch):
    for top in patch:
        if top not in ("meta", "phases", "tasks"):
            return "unknown patch section %r" % top
    for k in (patch.get("meta") or {}):
        if k not in _META_KEYS:
            return "meta.%s is not editable here" % k
    for _pid, pv in (patch.get("phases") or {}).items():
        for k in (pv or {}):
            if k not in _PHASE_KEYS:
                return "phase.%s is not editable here" % k
    for _tid, tv in (patch.get("tasks") or {}).items():
        for k in (tv or {}):
            if k not in _TASK_KEYS:
                return "task.%s is not editable here" % k
    return None


def apply_composition_patch(manifest, patch):
    """Apply an allow-listed composition patch to `manifest` in place.
    Returns None on success or an error string. Never touches structure."""
    err = _reject_unknown(patch)
    if err:
        return err
    meta = manifest.setdefault("meta", {})
    for k in _META_KEYS:
        if k in (patch.get("meta") or {}):
            meta[k] = patch["meta"][k]
    by_pid = {p.get("id"): p for p in (manifest.get("phases") or [])
              if isinstance(p, dict)}
    for pid, pv in (patch.get("phases") or {}).items():
        ph = by_pid.get(pid)
        if ph is None:
            return "unknown phase %r" % pid
        if "reviewModel" in (pv or {}):
            rev = ph.get("review")
            if not isinstance(rev, dict):
                rev = ph["review"] = {}
            rev["model"] = pv["reviewModel"]
    by_tid = {t.get("id"): t for p in (manifest.get("phases") or [])
              if isinstance(p, dict)
              for t in (p.get("tasks") or []) if isinstance(t, dict)}
    for tid, tv in (patch.get("tasks") or {}).items():
        t = by_tid.get(tid)
        if t is None:
            return "unknown task %r" % tid
        if "model" in (tv or {}):
            t["model"] = tv["model"]
        if "skills" in (tv or {}):
            sk = tv["skills"]
            # null is a legal VALUE, not a missing one (v0.37 B1): the explicit
            # opt-out that stops the area fallback. It is written as null so the
            # file says what the chips UI said ("none applies").
            if sk is not None and not (isinstance(sk, list)
                                       and all(isinstance(x, str) for x in sk)):
                return ("task %s skills must be an array of strings, or null "
                        "to say 'none applies'" % tid)
            t["skills"] = sk
    return None


def _touched_phase_ids(manifest, patch):
    """Which phases a patch actually changes — named directly, or owning a task."""
    touched = set((patch.get("phases") or {}).keys())
    want = set((patch.get("tasks") or {}).keys())
    if want:
        for ph in (manifest.get("phases") or []):
            if not isinstance(ph, dict):
                continue
            for t in (ph.get("tasks") or []):
                if isinstance(t, dict) and t.get("id") in want:
                    touched.add(ph.get("id"))
    return touched


def _write_back(project, mpath, raw_index, assembled, patch, touched):
    """Persist a patched manifest into whichever layout it is stored in.

    SINGLE FILE: write the assembled dict; it IS the file.

    SHARDED: write only what the patch touched — the body of each touched phase's
    shard, and the index only if `meta` changed. Two reasons this is targeted
    rather than a wholesale `save_sharded`:

      * The index stub is deliberately {id, title, shard} with no body mirror, and
        `_merge_phase` treats the shard as the source of truth. Writing a phase's
        `review.model` into the stub — which is what this used to do — put it
        somewhere the next load discards.
      * Rewriting untouched shards would renormalize files no one edited and
        manufacture merge conflicts against the parallel phase branches the
        sharded layout exists to keep conflict-free.

    Returns the list of written paths, project-relative.
    """
    if not _mio.is_sharded(raw_index):
        _atomic_write_json(mpath, assembled)
        return [os.path.relpath(mpath, project)]

    base = os.path.dirname(os.path.abspath(mpath))
    by_pid = {p.get("id"): p for p in (assembled.get("phases") or [])
              if isinstance(p, dict)}
    written = []
    for stub in (raw_index.get("phases") or []):
        if not isinstance(stub, dict) or stub.get("id") not in touched:
            continue
        patched = by_pid.get(stub.get("id"))
        if patched is None:
            continue
        if "shard" not in stub:
            continue          # inline phase in a sharded index: falls to the index write
        spath = os.path.abspath(os.path.join(base, stub["shard"]))
        if not _within(project, spath):
            raise ValueError("refused: shard path escapes project: %s" % stub["shard"])
        body = dict(patched)
        # The stub owns identity; the shard body never carries its own pointer.
        body.pop("shard", None)
        _atomic_write_json(spath, body)
        written.append(os.path.relpath(spath, project))

    if patch.get("meta"):
        idx = dict(raw_index)
        idx["meta"] = assembled.get("meta") or {}
        _atomic_write_json(mpath, idx)
        written.append(os.path.relpath(mpath, project))
    return written


def apply_composition(project, patch):
    """Load manifest, apply an allow-listed patch, validate, write it back.

    Reads through the dual-format loader and patches the ASSEMBLED manifest. It
    used to read the raw index instead, which on a sharded manifest — this repo's
    own, and the shipped example's — meant the phases were stubs with no tasks in
    them: every per-task edit was refused as "unknown task" for a task the panel
    had just listed, phase edits landed in a stub the next load throws away, and
    even a meta-only save failed on a wall of validator findings about stubs
    missing fields they are not supposed to have.
    """
    vm, _, _, _ = _cores()
    if not isinstance(patch, dict):
        return {"ok": False, "findings": ["patch must be a JSON object"]}
    config = read_config(project)
    mpath = _manifest_path(project, config)
    if not _within(project, mpath):
        return {"ok": False, "findings": ["refused: manifest path escapes project"]}
    if not os.path.isfile(mpath):
        return {"ok": False, "findings": ["manifest not found: run /audit:init first"]}
    try:
        raw_index = _read_json(mpath)
    except Exception as exc:
        return {"ok": False, "findings": ["cannot parse manifest: %s" % exc]}
    if not isinstance(raw_index, dict):
        return {"ok": False, "findings": ["manifest root is not an object"]}
    try:
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        return {"ok": False, "findings": ["cannot assemble manifest: %s" % exc]}
    if not isinstance(assembled, dict):
        return {"ok": False, "findings": ["manifest root is not an object"]}

    # Computed against the manifest as it is NOW, before the patch touches it: the
    # `from` half of every row has to be the value on disk, not the value the patch
    # is about to put there.
    applied = _composition_changes(assembled, patch)
    err = apply_composition_patch(assembled, patch)
    if err:
        return {"ok": False, "findings": ["refused: " + err]}
    # The heal rides a real write only (`applied` non-empty): an unchanged
    # save writes no file for it to ride, and the validator warning still
    # names the state for the reader. Validated AFTER healing -- the document
    # judged is the document written.
    healed = _heal_phase_status(assembled) if applied else []
    findings, warnings = vm.validate(assembled)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    if not applied:
        # A patch whose every field already holds the value it asks for. Writing it
        # would rewrite shards nobody edited — the exact renormalisation the
        # targeted write-back exists to avoid — to record no change at all.
        return {"ok": True, "findings": [], "warnings": warnings, "applied": [],
                "healed": [], "unchanged": True, "journaled": False,
                "journaledWhy": "unchanged", "written": [],
                "path": os.path.relpath(mpath, project),
                "layout": "sharded" if _mio.is_sharded(raw_index) else "single"}

    touched = _touched_phase_ids(assembled, patch)
    # A healed phase joins the write: in the sharded layout its status lives
    # in its own shard, which is only written for touched ids.
    touched.update(r["target"] for r in healed)
    sharded = _mio.is_sharded(raw_index)
    # Hold the lock across read-patch-write. Checking it and then writing left a
    # window an /audit run could start in; acquiring it closes that window with
    # the same O_EXCL primitive the CLI uses.
    lock = _acquire_write_lock(project, config,
                               touched if sharded else None)
    if lock.get("blocked"):
        return lock["response"]
    try:
        written = _write_back(project, mpath, raw_index, assembled, patch, touched)
    except ValueError as exc:
        return {"ok": False, "findings": [str(exc)]}
    finally:
        _release_write_lock(lock)
    out = {"ok": True, "findings": [], "warnings": warnings, "applied": applied,
           "healed": healed,
           "path": os.path.relpath(mpath, project),
           "layout": "sharded" if sharded else "single",
           "written": written}
    out.update(_journal(project, config, "composition.write",
                        out["path"], applied + healed))
    return out


# --- selftest -------------------------------------------------------------------
def _selftest():
    """The write-side cases, moved here with P12.4 and carrying their original
    labels. What stayed in panel-server.py is what asserts UI_HTML, an HTTP round
    trip, or panel-server's own source: those are claims about the server, not
    about what a save does to the files."""
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    import shutil as _shutil
    import tempfile

    # The read side this write path shares state with, reached the way panel-server
    # reaches it, so a case about the shared journal memo is about the real thing.
    areas_state = _panel_state.areas_state
    journal_state = _panel_state.journal_state
    policy_state = _panel_state.policy_state

    tmp = tempfile.mkdtemp(prefix="panel-write-selftest-")
    proj = os.path.join(tmp, "proj")

    # config write: valid then invalid
    res = write_config(proj, {"trivialLineThreshold": 40})
    check("write valid config ok", res["ok"] and os.path.isfile(_config_path(proj)))
    check("config on disk matches", read_config(proj).get("trivialLineThreshold") == 40)
    res = write_config(proj, {"trivialLineThreshold": 0})
    check("write invalid config rejected (not written)",
          not res["ok"] and read_config(proj).get("trivialLineThreshold") == 40)

    # manifest + composition patch
    mpath = _manifest_path(proj, read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    manifest = {"meta": {"version": 2, "reviewSkill": None},
                "phases": [{"id": "P1", "title": "P", "status": "pending",
                            "review": {"model": "sonnet"},
                            "tasks": [{"id": "P1.1", "title": "T",
                                       "status": "pending"}]}]}
    _atomic_write_json(mpath, manifest)

    res = apply_composition(proj, {"meta": {"reviewSkill": "user-skill"},
                                   "tasks": {"P1.1": {"skills": ["user-skill"], "model": "opus"}}})
    check("composition patch applied", res["ok"])
    saved = _read_json(mpath)
    check("reviewSkill written", saved["meta"]["reviewSkill"] == "user-skill")
    check("task skills written", saved["phases"][0]["tasks"][0]["skills"] == ["user-skill"])
    check("task model written", saved["phases"][0]["tasks"][0]["model"] == "opus")
    check("non-composition data preserved",
          saved["phases"][0]["title"] == "P" and saved["meta"]["version"] == 2)

    # structural edits refused
    res = apply_composition(proj, {"phases": {"P1": {"title": "HACKED"}}})
    check("structural phase edit refused", not res["ok"] and
          _read_json(mpath)["phases"][0]["title"] == "P")
    res = apply_composition(proj, {"bugs": []})
    check("unknown patch section refused", not res["ok"])
    res = apply_composition(proj, {"tasks": {"P9.9": {"model": "x"}}})
    check("unknown task id refused", not res["ok"])

    # a patch that would make the manifest invalid is rejected + not written
    res = apply_composition(proj, {"tasks": {"P1.1": {"skills": "notalist"}}})
    check("bad skills type refused", not res["ok"])

    # v0.37 B1: null is a WRITABLE value — the chips UI's "none applies" — and
    # it must land in the FILE as null (the opt-out that stops the area
    # fallback), not be refused as a bad type or flattened to [].
    res = apply_composition(proj, {"tasks": {"P1.1": {"skills": None}}})
    _t_null = _read_json(mpath)["phases"][0]["tasks"][0]
    check("skills null written - the opt-out lands in the file as null",
          res["ok"] and "skills" in _t_null and _t_null["skills"] is None)
    check("...and its change row reads list -> null through the view's own "
          "three-state normaliser",
          any(r.get("field") == "skills" and r.get("from") == ["user-skill"]
              and r.get("to") is None for r in res.get("applied") or []))
    res = apply_composition(proj, {"tasks": {"P1.1": {"skills": None}}})
    check("null on an already-opted-out task is unchanged, not a change - "
          "null and [] are two values, not one",
          res["ok"] and res.get("unchanged") is True)
    res = apply_composition(proj, {"tasks": {"P1.1": {"skills": []}}})
    _t_back = _read_json(mpath)["phases"][0]["tasks"][0]
    check("clearing the opt-out back to [] round-trips, with the row null -> []",
          res["ok"] and _t_back["skills"] == []
          and any(r.get("field") == "skills" and r.get("from") is None
                  and r.get("to") == [] for r in res.get("applied") or []))
    # Put the fixture back the way the cases below expect it.
    apply_composition(proj, {"tasks": {"P1.1": {"skills": ["user-skill"]}}})

    # lock respected
    open(mpath + ".lock", "w").close()
    res = apply_composition(proj, {"meta": {"reviewSkill": "x"}})
    check("write refused while locked", not res["ok"] and res.get("locked"))
    os.remove(mpath + ".lock")

    # --- the SHARDED layout ---------------------------------------------------
    # Everything above ran on a single-file manifest, and that is exactly why this
    # was broken in the field for so long: this repo's own manifest and the shipped
    # example are both sharded, and there the writer read the raw INDEX. Its phases
    # are stubs with no tasks in them, so every task edit was refused as "unknown
    # task" for a task the panel had just listed, phase edits went into a stub the
    # next load discards, and a meta-only save died on validator findings about
    # stubs missing fields stubs are not supposed to have.
    _sproj = tempfile.mkdtemp(prefix="panel-sharded-")
    try:
        _atomic_write_json(_config_path(_sproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _sm = _manifest_path(_sproj, read_config(_sproj))
        os.makedirs(os.path.dirname(_sm), exist_ok=True)
        _full = {"meta": {"version": 3, "reviewSkill": None},
                 "phases": [
                     {"id": "P1", "title": "One", "status": "pending",
                      "review": {"model": "sonnet"},
                      "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                     {"id": "P2", "title": "Two", "status": "pending",
                      "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]}
        _mio.save_sharded(_sm, _full)
        _idx = _read_json(_sm)
        check("sharded fixture really is sharded", _mio.is_sharded(_idx))
        _p2shard = os.path.join(os.path.dirname(_sm), _idx["phases"][1]["shard"])
        _p2_before = open(_p2shard, "rb").read()

        res = apply_composition(_sproj, {
            "meta": {"reviewSkill": "sk"},
            "phases": {"P1": {"reviewModel": "opus"}},
            "tasks": {"P1.1": {"model": "haiku", "skills": ["a"]}}})
        check("sharded: a task the panel listed can actually be edited", res["ok"])
        check("sharded: the response names the layout it wrote",
              res.get("layout") == "sharded")
        _re = _mio.load_manifest(_sm)
        _p1 = [p for p in _re["phases"] if p["id"] == "P1"][0]
        check("sharded: task model + skills survive a reload",
              _p1["tasks"][0].get("model") == "haiku"
              and _p1["tasks"][0].get("skills") == ["a"])
        check("sharded: per-phase review model lands in the shard, not the stub "
              "that _merge_phase throws away",
              _p1.get("review", {}).get("model") == "opus")
        check("sharded: meta lands on the index", _re["meta"]["reviewSkill"] == "sk")
        # The whole point of shards is that two phase branches never touch the same
        # file. A writer that rewrites every shard would renormalize files nobody
        # edited and manufacture exactly the conflicts the layout exists to avoid.
        check("sharded: an untouched phase's shard is not rewritten at all",
              open(_p2shard, "rb").read() == _p2_before)
        check("sharded: only the touched files are reported written",
              sorted(res.get("written") or []) == sorted(
                  [os.path.relpath(os.path.join(os.path.dirname(_sm),
                                                _idx["phases"][0]["shard"]), _sproj),
                   os.path.relpath(_sm, _sproj)]))
        # A meta-only save used to fail with ~22 findings about phase stubs.
        res = apply_composition(_sproj, {"meta": {"reviewSkill": "sk2"}})
        check("sharded: a meta-only save is not blocked by findings about stubs",
              res["ok"] and not res.get("findings"))
        check("sharded: unknown task still refused", not apply_composition(
            _sproj, {"tasks": {"P9.9": {"model": "x"}}})["ok"])
    finally:
        _shutil.rmtree(_sproj, ignore_errors=True)

    # --- v0.28: the areas registry over HTTP ------------------------------------
    # The GET cases (registry as stored, tags a phase uses, the typo case) moved to
    # _panel_state.py (P12.3); the WRITE path is what is exercised here.
    # `meta` lives on the INDEX in a sharded manifest, so a registry save must
    # touch the index and nothing else. That is the whole reason this goes through
    # apply_composition rather than writing the file itself: a second writer here
    # would be a second implementation of the targeted write-back, and the way it
    # would fail is by rewriting shards on a branch nobody is on.
    _aproj = tempfile.mkdtemp(prefix="panel-areas-")
    try:
        _atomic_write_json(_config_path(_aproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _am = _manifest_path(_aproj, read_config(_aproj))
        os.makedirs(os.path.dirname(_am), exist_ok=True)
        os.makedirs(os.path.join(_aproj, "services", "api"), exist_ok=True)
        _mio.save_sharded(_am, {
            "meta": {"version": 3,
                     "areas": {"api": {"root": "services/api", "description": "d",
                                       "reviewSkill": "backend-review"},
                               "unused": {"root": "services/api"}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "pending", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "apu",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})
        _aidx = _read_json(_am)
        _ashard = os.path.join(os.path.dirname(_am), _aidx["phases"][0]["shard"])
        _ashard_before = open(_ashard, "rb").read()

        _bad = write_areas(_aproj, {"areas": {"api": "services/api"}})
        check("areas PUT refuses a malformed registry, naming the entry",
              not _bad["ok"] and any("must be an object" in f
                                     for f in _bad["findings"]))
        check("...and a refused PUT wrote nothing",
              _read_json(_am)["meta"]["areas"].get("api") == {
                  "root": "services/api", "description": "d",
                  "reviewSkill": "backend-review"})
        # The shape is checked BEFORE the manifest is opened, and this is the case
        # that proves it rather than merely restating the validator: with a
        # manifest that cannot be parsed at all, the writer can only report the
        # parse error — so a caller who sent a bad body would be told nothing about
        # it, fix the manifest, and hit the same wall a second time.
        _saved = open(_am, "rb").read()
        with open(_am, "wb") as _fh:
            _fh.write(b"{ this is not json")
        _both = write_areas(_aproj, {"areas": {"api": "services/api"}})
        check("a malformed registry is named even when the manifest itself cannot "
              "be read - one round trip, both problems",
              not _both["ok"] and any("must be an object" in f
                                      for f in _both["findings"]))
        check("...while a WELL-formed registry over an unreadable manifest reports "
              "the manifest, so the two failures are never confused",
              any("cannot parse manifest" in f for f in
                  write_areas(_aproj, {"areas": {"api": {"root": "x"}}})["findings"]))
        with open(_am, "wb") as _fh:
            _fh.write(_saved)

        _res = write_areas(_aproj, {"areas": {"api": {"root": "services/api"},
                                              "web": {"root": "services/api"}}})
        check("areas PUT writes through the one composition writer", _res["ok"])
        check("areas PUT echoes the change as a row the confirm flow can print",
              [r["field"] for r in _res.get("applied") or []] == ["areas"])
        check("areas PUT touches the INDEX only - meta lives there, and rewriting "
              "a phase shard would manufacture a conflict on a branch nobody is on",
              _res.get("written") == [os.path.relpath(_am, _aproj)]
              and open(_ashard, "rb").read() == _ashard_before)
        _after = _read_json(_am)["meta"]["areas"]
        check("areas PUT replaces the registry wholesale, so dropping an area is "
              "an ordinary edit rather than something the API cannot express",
              set(_after) == {"api", "web"})
        check("...and the dropped area's phase tag now reads unregistered",
              {t["tag"]: t["registered"] for t in areas_state(_aproj)["tags"]}
              == {"api": True, "apu": False, "web": True})
        check("areas PUT accepts the bare registry as well as {areas: ...} - both "
              "readings of 'PUT the areas' are reasonable",
              write_areas(_aproj, {"api": {"root": "services/api"}})["ok"])
        _res = write_areas(_aproj, {"areas": {}})
        check("areas PUT can empty the registry", _res["ok"]
              and _read_json(_am)["meta"]["areas"] == {})
        check("a save that changes nothing still writes nothing",
              write_areas(_aproj, {"areas": {}}).get("unchanged") is True)
        _st2 = areas_state(_aproj)
        check("with no registry the tags list is still the truth about the phases",
              [t["tag"] for t in _st2["tags"]] == ["api", "apu"]
              and not any(t["registered"] for t in _st2["tags"]))
        _res = write_areas(_aproj, {"areas": {"api": {"root": "services/gone"}}})
        check("a root that is not on disk is written and WARNED about, not "
              "refused - the doctor reports it; the panel does not veto it",
              _res["ok"] and not areas_state(_aproj)["tags"][0]["rootExists"])
    finally:
        _shutil.rmtree(_aproj, ignore_errors=True)

    # --- v0.30: the capability policy ------------------------------------------
    # The rule-listing cases that are a pure function of the block, and the
    # enforcement-marker cases, moved to _panel_state.py (P12.3).
    # The resolution lives in _policy and is exercised there. What is checked here
    # is that this endpoint SHOWS what the guard hook will DO — same function, same
    # active areas — and that the one writer refuses what the validator refuses.
    # The GET half stays beside the PUT half rather than following the rest of the
    # read side: every one of these rows is read back AFTER a write_policy call,
    # off the fixture that write built, and splitting them would mean two copies of
    # that fixture asserting two halves of one round trip.
    _pproj = tempfile.mkdtemp(prefix="panel-policy-")
    try:
        os.makedirs(os.path.join(_pproj, ".claude"), exist_ok=True)
        # The capabilities this fixture resolves verdicts for are CREATED here,
        # project-local, rather than whatever `discover` happens to find on the
        # machine. A check that names `code-reviewer` because this laptop has one
        # installed is a check about the laptop: green here, absent on CI, and
        # silently vacuous either way.
        os.makedirs(os.path.join(_pproj, ".claude", "agents"), exist_ok=True)
        for _name in ("code-reviewer", "random-agent", "audit-executor"):
            with open(os.path.join(_pproj, ".claude", "agents", _name + ".md"),
                      "w", encoding="utf-8") as _fh:
                _fh.write("---\nname: %s\ndescription: fixture\n---\n" % _name)
        _atomic_write_json(os.path.join(_pproj, ".mcp.json"),
                           {"mcpServers": {"prod-db": {"command": "x"}}})
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _pm = _manifest_path(_pproj, read_config(_pproj))
        os.makedirs(os.path.dirname(_pm), exist_ok=True)
        _atomic_write_json(_pm, {
            "meta": {"version": 2, "areas": {"api": {"root": "."}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "in_progress", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "web",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})

        _ps = policy_state(_pproj)
        check("policy GET reports the shipped block as inert, so a repo that never "
              "opted in is not shown a governance surface that governs nothing",
              _ps["active"] is False and _ps["stored"] is None
              and _ps["policy"]["skills"]["default"] == "allow")
        check("policy GET resolves a verdict for every kind, even inert",
              set(_ps["resolved"]) == set(_policy.KINDS))
        check("policy GET reports the ACTIVE areas, which is what scopes an area "
              "rule - and only the phases with work in progress count",
              _ps["activeAreas"] == ["api"] and "web" in _ps["areas"])

        _bad = write_policy(_pproj, {"skills": {"default": "denied"}})
        check("policy PUT refuses a misspelled default in the policy's own words",
              not _bad["ok"] and any("policy.skills.default" in f
                                     for f in _bad["findings"]))
        check("...and a refused PUT wrote nothing",
              read_config(_pproj).get("policy") is None)
        # The policy is checked BEFORE the config is assembled, and this is the case
        # that proves it rather than restating the validator: with an unrelated
        # finding already in the file, a writer that only validated the assembled
        # config would answer with both — and the caller, who sent a policy, would
        # be told about a threshold they did not touch.
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json",
                            "trivialLineThreshold": 0})
        _only = write_policy(_pproj, {"skills": {"default": "denied"}})
        check("a bad policy is reported ALONE, even when the config it would join "
              "already has a finding of its own",
              not _only["ok"]
              and all(f.startswith("policy.") for f in _only["findings"]),
              )
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _req = write_policy(_pproj, {"agents": {"deny": ["audit:*"]}})
        check("policy PUT refuses a policy denying audit's own components - the "
              "line would not take effect, so saving it would leave a file that "
              "says something untrue",
              not _req["ok"] and any("not deniable" in f for f in _req["findings"]))
        check("...and that refusal is the VALIDATOR's, so the panel and the CLI "
              "cannot disagree about what is saveable",
              any("not deniable" in f for f in
                  _cores()[1].validate_config({"policy": {"agents": {
                      "deny": ["audit:*"]}}})[0]))

        _res = write_policy(_pproj, {"skills": {"default": "deny",
                                                "allow": ["dataviz"]}})
        check("policy PUT writes through the one config writer", _res["ok"])
        check("...which echoes the change as rows the confirm flow can print",
              any(r["field"].startswith("policy.")
                  for r in _res.get("applied") or []),
              )
        check("...and reports the journal outcome like every other save",
              "journaled" in _res)
        check("the block landed in the config file itself",
              read_config(_pproj)["policy"]["skills"]["default"] == "deny")
        check("a save that changes nothing writes nothing",
              write_policy(_pproj, {"skills": {"default": "deny",
                                               "allow": ["dataviz"]}}
                           ).get("unchanged") is True)
        check("policy PUT accepts {policy: ...} as well as the bare block",
              write_policy(_pproj, {"policy": {"skills": {"default": "allow"}}})["ok"])
        check("policy PUT can empty the block back to inert",
              write_policy(_pproj, {})["ok"]
              and policy_state(_pproj)["active"] is False)

        # The preview IS the guard's answer. Asserted against _policy.resolve rather
        # than against a second expectation written here: a check whose oracle is a
        # copy of the thing under test proves only that two copies agree.
        # `deny: ["*"]` would be refused by the writer — it matches audit's own
        # names — so the deny-everything shape is written the way the validator
        # accepts it: a default of deny, which `resolve` reaches only after the
        # required check has already let audit's own through.
        write_policy(_pproj, {"skills": {"default": "deny", "allow": ["dataviz"]},
                              "agents": {"default": "deny",
                                         "areas": {"api": {"allow": ["code-*"]},
                                                   "web": {"allow": ["never-*"]}}}})
        _ps = policy_state(_pproj)
        _pol = _policy.policy_cfg(read_config(_pproj))
        _rows = _ps["resolved"]["agents"]
        # `.get`, not `[...]`: a row that is missing is exactly what a broken
        # endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _by_pre = lambda rows: {r["name"]: r for r in rows}       # noqa: E731
        check("every resolved row is exactly what the guard hook would decide, "
              "including the basis it would print",
              bool(_rows) and all(
                  r["verdict"] == _policy.resolve(
                      _pol, "agents", r["name"], active_tags=["api"])["verdict"]
                  and r["basis"] == _policy.resolve(
                      _pol, "agents", r["name"], active_tags=["api"])["basis"]
                  for r in _rows))
        check("audit's own agent is marked required and allowed through a policy "
              "that denies everything - and it is the FIXTURE's copy, not one this "
              "machine happens to have installed",
              (_by_pre(_rows).get("audit-executor") or {}).get("required") is True
              and (_by_pre(_rows).get("audit-executor") or {}).get("verdict")
              == "allow")
        check("somebody else's agent under the same policy resolves to a violation",
              (_by_pre(_rows).get("random-agent") or {}).get("verdict")
              == "violation")
        # The preview must apply the ACTIVE areas, not merely the project-wide
        # rules: `api` has a phase in progress and `web` does not, so one area's
        # allow list is in force and the other's is not. Resolved with no active
        # areas at all, every one of these rows would read "violation".
        _by = _by_pre(_rows)
        check("an area's allow list is applied because that area has work in "
              "progress, and the row says which area answered",
              (_by.get("code-reviewer") or {}).get("verdict") == "allow"
              and (_by.get("code-reviewer") or {}).get("area") == "api",
              )
        check("...while an area with nothing running grants nothing",
              all(r["area"] != "web" for r in _rows))
        check("an MCP row is a STAND-IN for the whole server and says so, since "
              "what is discoverable is a server name and a policy matches tool "
              "names - and there IS a row, so this is not vacuously true",
              "mcp__prod-db__*" in [r["name"] for r in _ps["resolved"]["mcp"]]
              and all(r["standIn"] and r["name"].startswith("mcp__")
                      and r["name"].endswith("__*")
                      for r in _ps["resolved"]["mcp"]))

        # --- panel c7: what the switchboard needs beyond the verdicts ----------
        # The switches on that form can only write EXACT names. Everything else a
        # policy may legally contain — a glob, a rule for something nobody has
        # installed, a rule for a dormant area — is invisible to them, and the PUT
        # replaces the block WHOLESALE. A rule the form cannot show is therefore a
        # rule it would silently destroy, which is why the raw block travels too.
        _rules = _ps["rules"]["agents"]
        check("every pattern in the block is reported, in the order resolve reads "
              "them: deny before allow, project before area",
              [(r["scope"], r["list"], r["pattern"]) for r in _rules]
              == [("api", "allow", "code-*"), ("web", "allow", "never-*")])
        # Counted against `_policy.matches` over the rows this endpoint served, not
        # against a number written here: the machine running this has its own agents
        # installed, and "code-* matches exactly one" would be a claim about the
        # laptop — true here, false on CI, and vacuous either way.
        _codes = [r["name"] for r in _rows if _policy.matches(r["name"], ["code-*"])]
        check("...and each says what it matches TODAY, through the same matcher the "
              "guard matches with",
              "code-reviewer" in _codes
              and [r["n"] for r in _rules if r["pattern"] == "code-*"]
              == [len(_codes)])
        # A rule that matches nothing is the one a table of capabilities cannot
        # show at all, and the one most likely to be a typo. Dropping it here would
        # be the form quietly deleting it on the next save.
        check("a pattern matching nothing installed is still listed, and says it "
              "matches nothing rather than being left out",
              [r["n"] for r in _rules if r["pattern"] == "never-*"] == [0])

        # Every area a rule can be aimed at, and whether it decides anything today.
        _ainfo = {a["tag"]: a for a in _ps["areaInfo"]}
        check("the area columns cover every tag a rule could name, and mark which "
              "are live - an area rule is inert until that area has work in "
              "progress, and a column that does not say so is a trap",
              sorted(_ainfo) == _ps["areas"]
              and _ainfo["api"]["active"] is True
              and _ainfo["web"]["active"] is False)
        check("...and say which of them the registry actually knows, since a rule "
              "may legitimately be written for a free-text tag",
              _ainfo["api"]["registered"] is True
              and _ainfo["web"]["registered"] is False)

    finally:
        _shutil.rmtree(_pproj, ignore_errors=True)

    check("meta.areas is on the composition allow-list, so it goes through the "
          "writer that locks, validates and journals", "areas" in _META_KEYS
          and _reject_unknown({"meta": {"areas": {}}}) is None)
    check("...and nothing else was let in with it",
          _reject_unknown({"meta": {"phases": {}}}) is not None)

    # --- c6: what a save would change, who is making it, and the record of it ---
    # The rows the confirm dialog lists ARE the rows the server echoes as
    # `applied`; the client compares the two. Everything below is about those two
    # lists being computable from the same pair of values. (The dialog's own half —
    # the JS that builds them — is pinned in panel-server, beside UI_HTML.)
    check("a leaf path per row, not a block per row",
          _flat_paths({"usage": {"bands": {"highUSD": 1}}, "enforce": True})
          == {"usage.bands.highUSD": 1, "enforce": True})
    check("an empty object is a leaf, so emptying a block is still a change",
          _flat_paths({"usage": {}}) == {"usage": {}})
    check("a list is a leaf: a changed list is one row, not one row per element",
          _flat_paths({"secretPatterns": {"extra": ["a", "b"]}})
          == {"secretPatterns.extra": ["a", "b"]})
    # The WHOLE path, not the leaf's own name: `highUSD` alone would not say which
    # of the settings called that had moved.
    check("config diff names the dotted path and both sides",
          _config_changes({"usage": {"bands": {"highUSD": 1}}},
                          {"usage": {"bands": {"highUSD": 2}}})
          == [{"target": "config", "field": "usage.bands.highUSD",
               "from": 1, "to": 2}])
    check("config diff: an untouched key is not a change",
          _config_changes({"a": 1, "b": 2}, {"a": 1, "b": 3})
          == [{"target": "config", "field": "b", "from": 2, "to": 3}])
    # Deleting a key is how "use the default" is written, and a key whose value was
    # already null would vanish from a diff that only compared .get() results.
    check("config diff: removing a null key is still a change",
          [r["field"] for r in _config_changes({"x": None}, {})] == ["x"])

    _cm = _mio.load_manifest(mpath)
    check("composition diff reads `from` off the manifest, not off the patch",
          _composition_changes(_cm, {"tasks": {"P1.1": {"model": "haiku"}}})
          == [{"target": "P1.1", "field": "model",
               "from": "opus", "to": "haiku"}])
    check("composition diff drops a field set back to what it already held",
          _composition_changes(_cm, {"tasks": {"P1.1": {"model": "opus"}}}) == [])
    check("composition diff covers meta and the per-phase review model",
          [(r["target"], r["field"]) for r in _composition_changes(_cm, {
              "meta": {"reviewSkill": "other"},
              "phases": {"P1": {"reviewModel": "haiku"}}})]
          == [("meta", "reviewSkill"), ("P1", "review model")])
    check("composition diff skips an unknown id (the patch refuses it a line later)",
          _composition_changes(_cm, {"tasks": {"P9.9": {"model": "x"}}}) == [])
    # The `from` side has to be the value the FORM shows. _composition_view turns a
    # missing skills key into [], so reading the raw None here would make adding a
    # skill read as `null -> [a]` on the server and `[] -> [a]` in the browser, and
    # the panel would warn about a disagreement that is only a normalisation.
    _nos = {"meta": {}, "phases": [{"id": "PX", "tasks": [{"id": "PX.1"}]}]}
    check("composition diff normalises skills exactly as the view does",
          _composition_changes(_nos, {"tasks": {"PX.1": {"skills": ["a"]}}})
          == [{"target": "PX.1", "field": "skills", "from": [], "to": ["a"]}]
          and _panel_state._composition_view(_nos)["tasks"][0]["skills"] == [])
    check("composition diff: an empty skills list set to empty is not a change",
          _composition_changes(_nos, {"tasks": {"PX.1": {"skills": []}}}) == [])

    # The response the client compares against.
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("a composition save echoes exactly what it applied",
          res["ok"] and res["applied"] == [{"target": "P1.1", "field": "model",
                                            "from": "opus", "to": "sonnet"}])
    _mtime = os.path.getmtime(mpath)
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("a save that changes nothing writes nothing and says so",
          res["ok"] and res.get("unchanged") is True and res["applied"] == []
          and res.get("written") == [] and os.path.getmtime(mpath) == _mtime)
    _cfg_now = read_config(proj)
    res = write_config(proj, dict(_cfg_now))
    check("the same rule for the config: nothing changed, nothing written",
          res["ok"] and res.get("unchanged") is True and res["applied"] == [])
    res = write_config(proj, dict(_cfg_now, trivialLineThreshold=41))
    check("a config save echoes the dotted path it changed",
          res["ok"] and res["applied"] == [
              {"target": "config", "field": "trivialLineThreshold",
               "from": 40, "to": 41}])

    # --- the journal call site ---------------------------------------------------
    # This call site shipped in v0.28, one release BEFORE audit-journal.py, and was
    # exercised against the stubs below so it would not be untested code in the
    # meantime. The module is here now, so the last case in this block is the real
    # thing end to end — but the stubs stay: they are the only way to reach the two
    # fail-soft branches, and "the journal is absent" is still what an older
    # install looks like.
    _saved_j0 = dict(_JOURNAL)
    try:
        _JOURNAL.update({"tried": True, "mod": None})
        check("no journal on this install -> journaled false, and it says WHY",
              _journal(proj, read_config(proj), "config.write", "x", [])
              == {"journaled": False, "journaledWhy": "unavailable"})
    finally:
        _JOURNAL.clear()
        _JOURNAL.update(_saved_j0)
    check("...and on THIS install there is one, so the load resolves to the "
          "module rather than to None (the case above is a simulation now)",
          _journalmod() is not None and hasattr(_journalmod(), "append"))

    class _JStub(object):
        rows = []

        @staticmethod
        def append(project, entry):
            _JStub.rows.append((project, entry))
            return True

    class _JBroken(object):
        @staticmethod
        def append(project, entry):
            raise RuntimeError("disk on fire")

    _saved_j = dict(_JOURNAL)
    try:
        _JOURNAL.update({"tried": True, "mod": _JStub})
        _rows = [{"target": "P1.1", "field": "model",
                  "from": "opus", "to": "sonnet"}]
        out = _journal(proj, read_config(proj), "composition.write", "m.json", _rows)
        _ent = _JStub.rows[-1][1] if _JStub.rows else {}
        check("with a journal present the row is appended and reported",
              out == {"journaled": True} and len(_JStub.rows) == 1)
        check("the journal row carries the contract's fields, not this file's",
              _ent.get("action") == "composition.write"
              and _ent.get("target") == "m.json"
              and set(_ent) == {"action", "target", "summary", "actor"})
        check("the actor is the viewer, tagged with how the write arrived",
              (_ent.get("actor") or {}).get("via") == "panel"
              and (_ent.get("actor") or {}).get("sessionId") == _panel_session())
        check("the changes travel in the summary the row does have room for",
              "P1.1 model: opus -> sonnet" in (_ent.get("summary") or "")
              and (_ent.get("summary") or "").startswith("1 change(s)"))
        # The stub is swapped into a memo the READ side owns, and this is the case
        # that says the two are one object rather than two: `journal_state` has to
        # see the same install this writer sees, or each side would be testing a
        # journal the other does not have.
        check("the stub the writer swapped in is the module the READ side resolves "
              "to - one memo, reached by identity, not a copy per module",
              _JOURNAL is _panel_state._JOURNAL
              and _panel_state._journalmod() is _JStub)
        _JOURNAL.update({"tried": True, "mod": _JBroken})
        # Caught HERE as well: "fail-soft" means the exception does not leave
        # _journal, so a version that let it through would take this suite down
        # with a traceback instead of failing the one case that is about it.
        try:
            _fs = _journal(proj, read_config(proj), "x", "y", [])
        except Exception as exc:                                # pragma: no cover
            _fs = "it raised: %s" % exc
        check("a journal that throws never breaks the write it is recording",
              _fs == {"journaled": False, "journaledWhy": "failed"})
        _JOURNAL.update({"tried": True, "mod": _JStub})
        _JStub.rows = []
        res = apply_composition(proj, {"tasks": {"P1.1": {"model": "opus"}}})
        check("a real save appends one row and reports journaled",
              res["ok"] and res.get("journaled") is True and len(_JStub.rows) == 1)

        # --- the write heals "task in_progress, phase pending" (v0.37 A4) ----
        # The validator's warning stays as the backstop for hand edits; at the
        # plugin's own write site the class dies: a manifest a save persists
        # never leaves a phase 'pending' around a task that is already
        # running, and the journal row for that write says so.
        _hproj = tempfile.mkdtemp(prefix="panel-heal-")
        try:
            _atomic_write_json(_config_path(_hproj),
                               {"manifestPath": "docs/audit/audit-plan.json"})
            _hm = _manifest_path(_hproj, read_config(_hproj))
            os.makedirs(os.path.dirname(_hm), exist_ok=True)
            _atomic_write_json(_hm, {
                "meta": {"version": 2},
                "phases": [
                    {"id": "P1", "title": "One", "status": "pending",
                     "tasks": [{"id": "P1.1", "title": "T1",
                                "status": "in_progress"}]},
                    {"id": "P2", "title": "Two", "status": "in_progress",
                     "tasks": [{"id": "P2.1", "title": "T2",
                                "status": "in_progress"}]}]})
            _JStub.rows = []
            _hres = apply_composition(_hproj,
                                      {"tasks": {"P1.1": {"model": "opus"}}})
            _hdoc = _read_json(_hm)
            check("heal: a save that persists an in_progress task under a "
                  "pending phase flips the phase in the SAME write",
                  _hres.get("ok") is True
                  and _hdoc["phases"][0]["status"] == "in_progress")
            check("heal: the healed row is reported apart from `applied`, so "
                  "the confirm-echo comparison keeps meaning what it says",
                  _hres.get("healed") == [{"target": "P1", "field": "status",
                                           "from": "pending",
                                           "to": "in_progress"}]
                  and all(r.get("field") != "status"
                          for r in _hres.get("applied") or []))
            _hsum = (_JStub.rows[-1][1].get("summary")
                     if _JStub.rows else "") or ""
            check("heal: the journal row for that write says so",
                  "P1 status: pending -> in_progress" in _hsum)
            check("heal: a phase already in_progress is untouched",
                  _hdoc["phases"][1]["status"] == "in_progress"
                  and all(r.get("target") != "P2"
                          for r in _hres.get("healed") or []))
        finally:
            _shutil.rmtree(_hproj, ignore_errors=True)

        # Sharded: a phase's status lives in its own shard, so the heal must
        # write a shard the patch never touched -- or it would claim a heal
        # the next load cannot see.
        _hs = tempfile.mkdtemp(prefix="panel-heal-sharded-")
        try:
            _atomic_write_json(_config_path(_hs),
                               {"manifestPath": "docs/audit/audit-plan.json"})
            _hsm = _manifest_path(_hs, read_config(_hs))
            os.makedirs(os.path.dirname(_hsm), exist_ok=True)
            _mio.save_sharded(_hsm, {
                "meta": {"version": 3},
                "phases": [
                    {"id": "P1", "title": "One", "status": "pending",
                     "tasks": [{"id": "P1.1", "title": "T1",
                                "status": "pending"}]},
                    {"id": "P2", "title": "Two", "status": "pending",
                     "tasks": [{"id": "P2.1", "title": "T2",
                                "status": "in_progress"}]}]})
            _hres2 = apply_composition(_hs,
                                       {"tasks": {"P1.1": {"model": "opus"}}})
            _hp2 = [p for p in _mio.load_manifest(_hsm)["phases"]
                    if p["id"] == "P2"][0]
            check("heal: sharded - the healed phase's shard is written even "
                  "when the patch never touched that phase",
                  _hres2.get("ok") is True
                  and _hp2["status"] == "in_progress"
                  and any("P2" in w for w in _hres2.get("written") or []))
        finally:
            _shutil.rmtree(_hs, ignore_errors=True)
    finally:
        _JOURNAL.clear()
        _JOURNAL.update(_saved_j)

    # --- ...and the same path with the REAL module behind it (v0.29) ------------
    # The stubs above prove the call site. They cannot prove that a save produces a
    # row anyone can verify, which is the only claim this feature actually makes —
    # so this drives the panel's own writer, then asks audit-journal.py, not the
    # panel, whether the chain holds.
    _jmod = _journalmod()
    _before = len(_jmod.read_all(proj, read_config(proj)))
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "haiku"}}})
    _after = _jmod.read_all(proj, read_config(proj))
    check("a real composition save appends a real row and says it was logged",
          res.get("journaled") is True and len(_after) == _before + 1)
    _row = _after[-1] if _after else {}
    check("the row names the change in the same words the dialog showed",
          "P1.1 model:" in (_row.get("summary") or "")
          and "haiku" in (_row.get("summary") or ""))
    check("...and it names the panel as the writer, with the viewer as the author",
          (_row.get("actor") or {}).get("via") == "panel"
          and (_row.get("actor") or {}).get("author")
          == _viewer(proj, read_config(proj)).get("author"))
    check("the row records the manifest as it stood after the write - which is "
          "what makes a later change with no row to explain it visible",
          bool(_row.get("stateHash")))
    _jv = _jmod.verify(proj, read_config(proj))
    check("the chain the panel wrote verifies",
          _jv["ok"] and not _jv["findings"])
    _jst = journal_state(proj)
    check("GET /api/journal reports the rows newest first, with the verdict beside "
          "them - a list with no verdict invites trust, a verdict with no list is "
          "a claim about something you cannot see",
          _jst["available"] and _jst["verify"]["ok"]
          and _jst["rows"] and _jst["rows"][0].get("hash") == _row.get("hash"))
    check("...and the verdict counts the rows the reader actually sees - a "
          "hardcoded `ok` beside a list nobody checked is the failure this "
          "endpoint exists to avoid",
          _jst["verify"]["rows"] == len(_after) and _jst["verify"]["exists"])
    check("...and it says where the journal is, relative to the project",
          isinstance(_jst["dir"], str) and not os.path.isabs(_jst["dir"]))
    _saved_j2 = dict(_JOURNAL)
    try:
        _JOURNAL.update({"tried": True, "mod": None})
        _jst0 = journal_state(proj)
        check("an install with no journal module answers `not available` rather "
              "than 404 - there being no journal here is an answer",
              _jst0["available"] is False and _jst0["rows"] == []
              and _jst0["verify"] is None)
    finally:
        _JOURNAL.clear()
        _JOURNAL.update(_saved_j2)
    # A config save is journalled too, under its own action.
    _cfg_j = read_config(proj)
    write_config(proj, dict(_cfg_j, trivialLineThreshold=43))
    _acts = [r.get("action") for r in _jmod.read_all(proj, read_config(proj))]
    check("a config save is recorded under its own action - the rules changing is "
          "not the same event as the plan changing",
          "config.write" in _acts and "composition.write" in _acts)
    # Off means off, on both surfaces.
    write_config(proj, dict(read_config(proj), journal={"enabled": False}))
    _n_off = len(_jmod.read_all(proj, read_config(proj)))
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("with journal.enabled false a save still succeeds, writes no row, and "
          "does NOT claim to have been logged",
          res["ok"] and res.get("journaled") is False
          and len(_jmod.read_all(proj, read_config(proj))) == _n_off)
    write_config(proj, dict(read_config(proj), journal={"enabled": True}))

    check("a change renders the same way for the journal as for the dialog",
          _fmt_change({"target": "P1.2", "field": "model",
                       "from": None, "to": "opus"}) == "P1.2 model: (unset) -> opus"
          and _fmt_change({"target": "P1.2", "field": "skills",
                           "from": [], "to": ["a"]}) == 'P1.2 skills: [] -> ["a"]')
    check("on a skills row, null is the OPT-OUT, not '(unset)' - the journal "
          "must record the one deliberate answer as an answer",
          _fmt_change({"target": "P1.2", "field": "skills",
                       "from": [], "to": None})
          == "P1.2 skills: [] -> null (opted out)"
          and _fmt_change({"target": "P1.2", "field": "model",
                           "from": None, "to": "opus"})
          == "P1.2 model: (unset) -> opus")
    check("...including a boolean, which the browser spells `true` and str() "
          "spells `True` - a value nobody can type into the JSON file they are "
          "being told about",
          _fmt_change({"target": "config", "field": "enforce",
                       "from": False, "to": True})
          == "config enforce: false -> true")
    check("a number is not quoted and a string is not JSON-escaped - the line is "
          "prose about a JSON file, not JSON",
          _fmt_change({"target": "config", "field": "trivialLineThreshold",
                       "from": 40, "to": 41})
          == "config trivialLineThreshold: 40 -> 41"
          and "\"opus\"" not in _fmt_change({"target": "t", "field": "model",
                                             "from": "a", "to": "opus"}))

    # --- isolation cases (P12.4): the moved boundary stays real -----------------
    _src = _src_of_this_file()
    _imports = [l for l in _src.split("\n")
                if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server - the write path sits BELOW the "
          "server and ABOVE the read side, so nothing here can form a cycle",
          not any("panel_server" in l or "panel-server" in l for l in _imports))
    _panel_src = open(os.path.join(_HERE, "panel-server.py"), encoding="utf-8").read()
    _moved = ["_atomic_write_json", "write_policy", "write_areas", "_panel_session",
              "_acquire_write_lock", "_release_write_lock", "_flat_paths",
              "_config_changes", "_composition_changes", "_fmt_change", "_journal",
              "write_config", "_reject_unknown", "apply_composition_patch",
              "_touched_phase_ids", "_write_back", "apply_composition"]
    _unaliased = [n for n in _moved
                  if "\n%s = _panel_write.%s\n" % (n, n) not in _panel_src]
    check("every name this module took is aliased back in panel-server, so a route "
          "or a selftest that still spells it there resolves to THIS one: %r"
          % (_unaliased,), not _unaliased)
    check("...and every one of them is actually defined here rather than merely "
          "expected: %r" % ([n for n in _moved if n not in globals()],),
          len([n for n in _moved if n in globals()]) == len(_moved))
    # The journal memo, pinned from this side too: panel-server aliases _panel_STATE's
    # dict, this module reaches the same one, and all three are one object. Two
    # memos would be two answers to "is there a journal on this install".
    check("the journal memo is the read side's, shared by identity with "
          "panel-server rather than copied into a third dict",
          _JOURNAL is _panel_state._JOURNAL
          and "\n_JOURNAL = _panel_state._JOURNAL\n" in _panel_src)

    _shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    print(__doc__.strip())
