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
panel-server -- one of its cases says so. The DAG is
_panel_state -> _panel_write -> panel-server.

panel-server.py keeps a thin module-level alias for every name moved here, so its
PUT/POST routes and the rest of the suite keep referring to them unchanged.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__panel_write.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. One of them reads panel-server.py's source
and pins all 17 alias lines this module's names are re-exported through, exactly
as written, so a rename on either side is caught rather than absorbed.

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
    case that swaps a stub module in by mutating it in place is seen by the
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
import tempfile

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

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (meta.areas registry + shared resolution)
import _policy                # noqa: E402  (the capability policy + its resolution)
import _ui_theme as _theme    # noqa: E402  (the token layer + the theme compiler)
import _panel_settings        # noqa: E402  (settings-form schema + write allow-lists)
import _panel_state           # noqa: E402  (the read side this write path reads through)
# The RULE, not the command that wraps it. Loading `materialize-proposal.py`
# here worked and was still wrong: this file sits below the entry points, so the
# edge pointed upward and `_deps.layer_violations()` said so by name.
import _proposals             # noqa: E402  (the proposal lifecycle + its lock)
import _locks                 # noqa: E402  (take and give back the index lock, at layer 1)
import _ado_parent            # noqa: E402  (where ONE item hangs; the no-declaration marker)
import _ado_tracked           # noqa: E402  (whether ONE item belongs on the board at all)
import _warning_groups as _wg  # noqa: E402  (the shape a repeated warning prints in)
import _priority              # noqa: E402  (what a valid tier is, and who holds tier 1 -
#                                            the SAME function set-priority.py asks)
import _gate_feed             # noqa: E402  (the plan-gate feed's prune rule, at layer 2 -
#                                            the SAME rule /audit:logs prune runs)
import _journal_io            # noqa: E402  (repo_relative_or_token: the redactor, at layer 1)
import _panel_discovery       # noqa: E402  (the inventory AND the portability verdict on it)
import _config_rules          # noqa: E402  (PORTABILITY_MODES: the enum this reads a tier from)
import _loader                # noqa: E402  (load_hooks_config: where the shipped default lives)

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


def _not_a_json_object():
    """The refusal every write endpoint gives a body that is not an object.

    A FUNCTION returning a fresh dict, not a module constant: a shared dict is
    module state a caller could append a finding to, and the next endpoint would
    return it. The same reason `findings` lists are built per call everywhere else
    here.

    It exists because the value was written out four times, byte for byte, at four
    endpoints - and a refusal is a contract with the front end, which reads `ok` and
    renders `findings`. Four copies of one contract is three chances to reword one
    of them and not the others. (The dict KEYS around it are repeated far more often
    and correctly so: `"findings"` at 39 sites is a key name, not a duplicated fact,
    and `out[_FINDINGS]` would be worse to read at every one of them.)
    """
    return {"ok": False, "findings": ["body must be a JSON object"]}


def _atomic_write_json(path, obj):
    """Thin delegation to the plugin's ONE atomic-JSON-write implementation
    (_manifest_io.atomic_write_json) — ensure_ascii=False keeps this module's
    existing byte shape unchanged."""
    _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)


# --- the CLI writers' shared machinery ------------------------------------------
# THREE FUNCTIONS AND A LOCK WRAPPER THAT ARE NOT THE PANEL'S, and they live here
# for the reason every other alias above does: this module is already the shared
# home the manifest-writing COMMANDS reach into (`audit-task.py` takes eight names
# from it). `set-priority.py` needs the same four, and the alternatives were both
# worse than a move — a copy in the second command is two rollbacks that will
# eventually disagree, and reaching `audit-task.py` through `_loader` is an entry
# point loading an entry point, which is the shape `KNOWN_LAYER_DEBT` exists to
# keep at zero new entries.
#
# `prefix` is a parameter on the lock wrapper because the message is the CLI's, not
# this module's: the lock library prints its OWN standard refusal and the caller
# adds only its next step.


def project_of_manifest(mpath):
    """The project root a NAMED manifest belongs to: the first ancestor of the
    manifest (starting at its own directory) that holds a `.claude/` dir or a
    `.git` entry.

    MARKERLESS fallback (F-C-2): when the manifest sits in the default layout
    (`<T>/docs/audit/<file>`), the root is `<T>` -- taking the manifest's own
    directory doubled the layout (the journal's default rel re-appended
    `docs/audit` under `.../docs/audit`). Anywhere else the root is the
    manifest's own directory. Either way the root stays INSIDE the named
    manifest's tree, never another repo's."""
    start = os.path.dirname(os.path.abspath(mpath))
    cur = start
    while True:
        if os.path.isdir(os.path.join(cur, ".claude")) \
                or os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if os.path.basename(start) == "audit" \
            and os.path.basename(os.path.dirname(start)) == "docs":
        return os.path.dirname(os.path.dirname(start))
    return start


def snapshot(paths):
    """{path: bytes-or-None} for everything a rollback must restore."""
    snap = {}
    for path in paths:
        try:
            with open(path, "rb") as fh:
                snap[path] = fh.read()
        except OSError:
            snap[path] = None
    return snap


def restore(snap):
    """Put every snapshotted file back byte-for-byte (temp + os.replace, the
    same atomicity the write had). A file that did not exist is removed."""
    for path, data in snap.items():
        if data is None:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def acquire_index_lock(project, config, mpath, takeover, out, prefix, note):
    """Take the index lock for a whole read-modify-write. Returns a lock handle
    dict, or an int exit code AFTER printing the lock module's own message --
    the standard shape a human already knows from audit-lock.py and the panel;
    the caller adds only its own next step.

    `_locks.acquire` (layer 1), not a loaded COMMAND. The old spelling built an
    argv for `audit-lock.py` and reached it through the panel's read-side
    accessor, which meant a very real dependency on the lock was attributed by
    `_deps` to whichever module held the literal. A hidden edge is not a retired
    one; this one is an import.
    """
    git_root = os.path.join(project, (config or {}).get("gitRoot") or ".")
    lines = []
    try:
        code = _locks.acquire(git_root, "index", note=note,
                              takeover=bool(takeover), out=lines.append)
    except Exception:
        code = None
    if code == 0:
        return {"held": True, "mod": _locks, "project": git_root}
    if code == _locks.E_LIVE:
        for line in lines:
            out(line)
        return _locks.E_LIVE
    if code == _locks.E_STALE:
        for line in lines:
            out(line)
        out("%s once a human has confirmed, rerun with --takeover." % prefix)
        return _locks.E_STALE
    # Not a git repo (or the lock library refused for a reason of its own): fall
    # through to the legacy working-tree lockfile -- guard a single clone rather
    # than writing unguarded (`_acquire_write_lock`'s precedent).
    legacy = mpath + ".lock"
    try:
        fd = os.open(legacy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        return {"held": True, "legacy": legacy}
    except FileExistsError:
        out("%s manifest is locked by a running /audit command (%s exists); try "
            "again once it finishes" % (prefix, os.path.basename(legacy)))
        return _locks.E_LIVE
    except OSError:
        return {"held": False}


def release_index_lock(lock):
    """Give the lock back. Never raises: a write that succeeded must not be
    reported as failed because the release did."""
    if not lock or not lock.get("held"):
        return
    try:
        if lock.get("legacy"):
            os.unlink(lock["legacy"])
            return
        lock["mod"].release(lock["project"], "index",
                            out=lambda *_a, **_k: None)
    except Exception:
        pass


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
        return _not_a_json_object()
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
        return _not_a_json_object()
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


def proposal_action(project, body):
    """`POST /api/proposal` - materialize, drop or revive a parked proposal.

    Calls `materialize-proposal.py`'s own `main`, exactly as `render_report` calls
    the renderer's: same code path the CLI and `/audit:propose` take, no
    interpreter discovery, and identical behaviour on Windows. The panel therefore
    adds NO rule of its own - the closure, the lock, the collision guard and the
    revalidation all happen in the one place that has cases for them.

    `plan` is the read-only half, and the tab calls it first so its confirm dialog
    can show what a materialization would pull in BEFORE anything is written.
    """
    # `isinstance`, not `body or {}`. That idiom covers `null`, `[]` and `""` -
    # everything falsy - and lets a TRUTHY non-object straight through to `.get`,
    # which is an AttributeError. `panel-server` wraps only the JSON PARSE in a
    # try/except, so a POST of `"x"` - valid JSON, wrong type - reached this line
    # and took the request handler down instead of being refused. The five sibling
    # endpoints all check the type; this was the one that did not, which is what
    # made the divergence worth a case over the whole set rather than a fix here.
    if not isinstance(body, dict):
        return _not_a_json_object()
    action = body.get("action")
    pid = (body or {}).get("id")
    if action not in ("plan", "materialize", "drop", "revive"):
        return {"ok": False,
                "findings": ["unknown proposal action %r" % (action,)]}
    if not isinstance(pid, str) or not pid.strip():
        return {"ok": False, "findings": ["no proposal id given"]}
    mpath = _manifest_path(project, read_config(project))
    if not mpath or not os.path.isfile(mpath):
        return {"ok": False,
                "findings": ["no manifest to act on - run /audit:init first"]}
    ok, payload = _proposals.run(
        mpath, action, [pid.strip()],
        policy=(body or {}).get("policy"),
        reason=(body or {}).get("reason"))
    if action == "plan":
        # A plan reports refusals IN THE PAYLOAD, so `ok` being false here is data
        # rather than an error: the tab renders "PROP-3 was dropped: …" in its
        # dialog instead of a generic failure. Every other action treats it as one.
        return {"ok": True, "plan": (payload.get("plan")
                                    or {"refused": [], "steps": []})}
    if not ok:
        # The rule's refusals are already worded for a reader (a dropped proposal
        # quotes why it was dropped), so they pass straight through.
        return {"ok": False, "findings": payload.get("findings") or ["refused"]}
    message = payload.get("message")
    lines = message if isinstance(message, list) else [message]
    return {"ok": True, "message": " · ".join(str(x) for x in lines if x),
            "warnings": payload.get("warnings") or []}


def write_ado(project, body):
    """`PUT /api/ado` — replace `meta.ado` (the connector config) wholesale.

    The `areas` pattern applied to the second API-only meta key. The shape is
    checked HERE, before anything is written — and through the manifest
    validator's OWN `check_ado_meta`, not a local copy, so the panel and the
    CLI cannot disagree about what a valid connector config is. The write then
    goes through `apply_composition`, the one writer: lock, re-validate,
    index-only patch (meta lives there), change rows, journal.

    `{"ado": null}` is a legal PUT — the connector reads off. Item links are
    sync's records, not this config's, and stay untouched.
    """
    vm, _, _, _ = _cores()
    if not isinstance(body, dict):
        return _not_a_json_object()
    ado = body.get("ado") if "ado" in body else body
    findings, warnings = vm.check_ado_meta(ado)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    res = apply_composition(project, {"meta": {"ado": ado}})
    if res.get("ok"):
        res["warnings"] = list(res.get("warnings") or []) + warnings
    return res


def prune_gate_events(project, body):
    """`POST /api/gate-events/prune` - clean the feed the Plan gate card renders.

    THE CARD IS WHERE THE ROWS ARE SHOWN, SO THE CONTROL BELONGS THERE. `_gate_feed`
    is the rule and `audit-logs.py` is the other door onto it; the panel adds no
    rule of its own, exactly as `proposal_action` adds none - the classification,
    the one file it may rewrite and the refusal all happen in the place that has
    cases for them, so the button and the command cannot disagree about what a
    prune removes.

    `{"dryRun": true}` is the confirm dialog's half: the same counts, nothing
    written. The client is expected to call it first and show what a prune WOULD
    take, which is the shape the proposal tab already uses.

    NO INDEX LOCK AND NO JOURNAL ROW, and both are decisions. The lock guards the
    manifest, and this touches no part of it. The journal is the manifest's
    tamper-evident trail; this feed is telemetry by its writer's own words
    (`append_gate_event`), so a row in the hash chain for a telemetry prune would
    put something in the evidence that the evidence does not cover.
    """
    if not isinstance(body, dict):
        return _not_a_json_object()
    older = body.get("olderThanDays")
    if older is not None and (isinstance(older, bool)
                              or not isinstance(older, int) or older < 1):
        # Refused rather than coerced or ignored: a threshold nobody can read is
        # the one input here that decides how much history goes.
        return {"ok": False,
                "findings": ["olderThanDays must be a whole number of days, at "
                             "least 1 (got %r)" % (older,)]}
    return _redacted_feed_answer(
        project, _gate_feed.prune(project, read_config(project),
                                  older_than_days=older,
                                  dry_run=bool(body.get("dryRun"))))


def _redacted_feed_answer(project, result):
    """`_gate_feed.prune`'s answer with the feed's own path made safe to paint.

    THE PAGE NOT RENDERING IT IS NOT A REASON TO SHIP IT RAW. `path` is
    `logs_dir()` joined onto the project root, so on a real machine it carries
    the operator's home directory and user name, and it travels in an HTTP
    response on the surface `docs/screenshots/panel-gate.png` is a committed
    render of. The previous release closed this same channel one card up
    (`_panel_runstate._redact_gate_row`, which redacts the events table this
    prune acts on), and a redactor scoped to the cell somebody happened to paint
    fails the moment the next reader looks one field further.

    REDACTED RATHER THAN DROPPED, and the two are not the same answer. The
    counts are a claim and the file they were counted in is the basis that makes
    the claim checkable, so dropping the field would leave the claim with no
    basis at all; `_gate_feed.prune` also documents every field as present on
    every outcome, and a panel answering in a different shape from
    `/audit:logs prune` would be a second contract for one rule.
    `repo_relative_or_token` keeps the basis and loses the machine - and its
    token says something the raw path did not, namely that `logsDir` points
    somewhere this repository does not contain.

    THE FINDINGS CARRY THE SAME BYTES, TWICE. `could not read %s: %s`
    interpolates the path and then an OSError that spells the same filename
    again, so the substitution runs over every finding rather than over the one
    key: the leak is the path, not the field it happens to sit under.

    A REFUSAL FROM `feed_path` NAMES `logsDir` AND LEAVES `path` AT None, so
    there is nothing here to match on. That sentence is `_gate_feed`'s to
    redact; it is left alone rather than half-cleaned, because a redactor that
    guessed at a substring it was not given would be a second rule.
    """
    if not isinstance(result, dict):
        return result
    shown = dict(result)
    raw = result.get("path")
    if not (isinstance(raw, str) and raw):
        return shown
    safe = _journal_io.repo_relative_or_token(project, raw)
    shown["path"] = safe
    findings = result.get("findings")
    if isinstance(findings, list):
        shown["findings"] = [f.replace(raw, safe) if isinstance(f, str) else f
                             for f in findings]
    return shown


# --- write locking ---------------------------------------------------------------
# The panel wears a different identity in each of the three places that need one,
# and F111 is what happens when one of them is reused for another:
#
#   the LOCK      `_panel_session()` -- a pid, because liveness is the question;
#   the JOURNAL   nothing. `_journal_io` falls through to its persisted
#                 per-checkout writer token, which is what names the committed
#                 file; `via: "panel"` says who wrote the row;
#   the CLAIM     `PANEL_JOURNAL_WRITER`, a fixed key -- one panel per project,
#                 so the claim is per project and not per process.
PANEL_JOURNAL_WRITER = "panel"


def _panel_session():
    """This panel's LOCK identity, and nothing else's.

    A pid the OS can vouch for is what lets a crashed panel's lock be judged dead
    rather than waited out for an hour. That is the whole reason it is a pid.

    IT MUST NOT NAME A COMMITTED FILE (F111). This value went to the journal as
    `actor.sessionId` too, and `_journal_io.writer_id()` takes a session id as the
    writer id -- so the trail's own committed file became `<month>.panel-<pid>`,
    a shape this plugin's own PII gate refuses, in the one field with no repair
    path (`genesis_prev()` seeds the chain from those bytes, so a committed name
    cannot be corrected without breaking `verify()` on every clone). It changed on
    every launch as well, scattering a month of panel edits across a file per
    panel process. `_journal` passes no session id at all now."""
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


def _nested_meta_rows(key, was, now):
    """Dotted, presence-aware rows for a NESTED meta key. null/absent flattens to
    no leaves, so configuring rows every leaf in and null-ing rows each one
    away; a transition both sides of which flatten empty (e.g. null -> {})
    still gets one whole-key row rather than silence.

    Takes the key rather than hard-coding it: `meta.ado` and `meta.branch` are the
    same shape of edit, and a second copy differing only in a string prefix is the
    shape that drifts. `_ado_rows` stays as the name `ado-connector.js` documents
    itself against.
    """
    a = _flat_paths(was) if isinstance(was, dict) else {}
    b = _flat_paths(now) if isinstance(now, dict) else {}
    rows = []
    for p in sorted(set(a) | set(b)):
        if (p in a) == (p in b) and a.get(p) == b.get(p):
            continue
        rows.append({"target": "meta", "field": key + "." + p,
                     "from": a.get(p), "to": b.get(p)})
    if not rows:
        rows.append({"target": "meta", "field": key, "from": was, "to": now})
    return rows


def _ado_rows(was, now):
    """`_nested_meta_rows` for `meta.ado` — the name `ado-connector.js` mirrors."""
    return _nested_meta_rows("ado", was, now)


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
            if was == now:
                continue
            if k in ("ado", "branch"):
                # The NESTED meta keys: dotted, presence-aware rows
                # (_config_changes' rule), so the confirm dialog prints
                # `ado.enabled true -> false` instead of two whole objects.
                rows.extend(_nested_meta_rows(k, was, now))
                continue
            rows.append({"target": "meta", "field": k, "from": was, "to": now})
    by_pid = {p.get("id"): p for p in (manifest.get("phases") or [])
              if isinstance(p, dict)}
    for pid, pv in sorted((patch.get("phases") or {}).items()):
        ph = by_pid.get(pid)
        if ph is None:
            continue
        if "reviewModel" in (pv or {}):
            rev = ph.get("review") if isinstance(ph.get("review"), dict) else {}
            was, now = rev.get("model"), pv["reviewModel"]
            if was != now:
                rows.append({"target": pid, "field": "review model",
                             "from": was, "to": now})
        if _priority.FIELD in (pv or {}):
            # `from` through `_priority.tier_of`, for `_skills_of`'s reason: the
            # dialog must show the value that is IN FORCE, and an invalid stored
            # value is in force as "unprioritised" rather than as itself.
            was, now = _priority.tier_of(ph), pv[_priority.FIELD]
            if was != now:
                rows.append({"target": pid, "field": _priority.FIELD,
                             "from": was, "to": now})
        if _ado_parent.FIELD in (pv or {}):
            # `from` is the MARKER when the phase declares nothing, never None:
            # null is a value here, so a `from` of None would render
            # "use the fallback -> nowhere" as "not set -> not set" and the one
            # row a reader most needs to see would be the row that looks like a
            # no-op. `_ado_parent_of`'s rule, spelled where the row is built
            # because `_panel_composition` is a layer-mate this file may not
            # import.
            was = (ph[_ado_parent.FIELD] if _ado_parent.FIELD in ph
                   else _ado_parent.use_fallback())
            now = pv[_ado_parent.FIELD]
            if was != now:
                rows.append({"target": pid, "field": _ado_parent.FIELD,
                             "from": was, "to": now})
        if _ado_tracked.FIELD in (pv or {}):
            # `from` is the STORED value or None, and here None really is the
            # absence: `adoTracked` is a boolean in the schema, so null is not a
            # value it can carry and the key's absence is the only thing it can
            # mean. That is the whole difference from the row above, and it is
            # why this one does not need a marker - `_ado_tracked_of`'s rule,
            # spelled here for the reason that one is.
            was = ph.get(_ado_tracked.FIELD)
            now = pv[_ado_tracked.FIELD]
            if was != now:
                rows.append({"target": pid, "field": _ado_tracked.FIELD,
                             "from": was, "to": now})
        if "area" in (pv or {}):
            # BOTH SIDES THROUGH `areas_of`, so the row compares what is in force
            # with what would be, in one spelling. Compared as the resolved TAG
            # LIST and not as the stored value: `"api"` and `["api"]` are the same
            # tagging, and a row saying `api -> ['api']` is a change the reader
            # cannot act on. The `to` side is rendered the way it will be STORED,
            # which is the string for one tag - the shape `audit-task` writes.
            was = _areas.areas_of(ph.get("area"))
            tags = _areas.areas_of(pv["area"])
            if was != tags:
                rows.append({"target": pid, "field": "area",
                             "from": (was[0] if len(was) == 1 else was) or None,
                             "to": (tags[0] if len(tags) == 1 else tags) or None})
    # `_mio.tasks_by_id` drops a task carrying no id, where this index used to key
    # it under `None`. Nothing reachable changes: the keys looked up here come out
    # of a JSON object, so they are always strings and could never BE `None` --
    # what goes away is the `None` entry sitting in the index waiting for a caller
    # that could hit it.
    by_tid = _mio.tasks_by_id(manifest)
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
    # The heal is its OWN guard against a second row for the same phase: the
    # moment the status is flipped the phase stops reading 'pending', so the rest
    # of its tasks fall out of this branch. That is what lets the walk be
    # `_mio.iter_tasks` -- one pass over (phase, task) pairs -- instead of a
    # per-phase `any()`, and phases still heal in document order.
    for ph, t in _mio.iter_tasks(manifest):
        if ph.get("status") != "pending" or t.get("status") != "in_progress":
            continue
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

    NO `sessionId` IN THE ACTOR, and that absence is the fix rather than an
    omission: `_panel_session()`'s docstring says why. Without one `_journal_io`
    names the file from its persisted per-checkout writer token, and `via` is
    what records that the panel wrote the row.
    """
    mod = _journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    try:
        written = mod.append(project, {
            "action": action,
            "target": target,
            "summary": "%d change(s): %s" % (
                len(rows), "; ".join(_fmt_change(r) for r in rows)),
            "actor": {"author": _viewer(project, config).get("author"),
                      "via": "panel"}})
    except Exception:
        written = False
    if not written:
        return {"journaled": False, "journaledWhy": "failed"}
    _claim_panel_write(mod, project, config, written)
    return {"journaled": True}


def _claim_panel_write(mod, project, config, written):
    """Leave the claim `guard-bash-writes` needs, so this append is not read as a
    shell write into the audit trail (F104). Returns the slot, or None.

    The panel server is a DETACHED process this plugin launched, so the guard's
    per-session sidecar can never name what it wrote: the operator's session did
    not write it. It gets a slot of its own under a fixed key, which the guard
    reads alongside the session's.

    THE PATH COMES FROM `append`, never from re-deriving a name here. Which file
    the row landed in is `_journal_io`'s answer -- it changed once already (F111)
    -- and a second guess at it would be a claim about a file that does not exist,
    which is silence dressed as evidence.

    Fail-soft like everything else on this path: a save that succeeded must not be
    reported as failed because the claim could not be left. An older journal
    module has no `record_plugin_write` and returns True rather than a path from
    `append`; both mean there is nothing to claim, not that the write failed."""
    if not isinstance(written, str):
        return None
    recorder = getattr(mod, "record_plugin_write", None)
    if recorder is None:
        return None
    try:
        return recorder(project, config, PANEL_JOURNAL_WRITER, written)
    except Exception:
        return None


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
                "path": _output.posix_rel(path, project)}
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
           "path": _output.posix_rel(path, project)}
    # `current`, not the config just written: the actor is resolved under the mode
    # that was in force when they made the change, not one this same save may have
    # altered.
    out.update(_journal(project, current, "config.write", out["path"], applied))
    return out


def theme_state(project):
    """`GET /api/theme` — the theme in effect, the vocabulary to edit it with,
    and the default to measure changes against.

    The DEFAULT ships in the payload rather than being re-derived in the
    browser: "what did I change" is theme-minus-default, and a second copy of
    the default in JS is how the two answers start disagreeing."""
    config = read_config(project)
    info = _theme.resolve_theme(project, config)
    stored = info["theme"] or {}
    return {
        "theme": stored,
        "default": _theme.DEFAULT_THEME,
        "groups": [{"key": k, "title": t, "tokens": list(names)}
                   for k, t, names in _theme.THEME_GROUPS],
        "single": sorted(_theme.THEME_SINGLE),
        "source": info["source"],
        "path": (_output.posix_rel(info["path"], project)
                 if info.get("path") else None),
        "name": info["name"],
        "error": info["error"],
        "warnings": _theme.contrast_warnings(stored) if stored else [],
        "layout": _theme.theme_layout(stored),
        "densities": sorted(_theme.DENSITIES),
        # Which themes this project can switch to — files on disk, plus the
        # built-in. A preset IS a saved file here; a registry beside them would
        # be a second list to keep in step.
        "saved": _theme.list_themes(project),
        # The cards a view is allowed to reorder, named by the renderer that
        # draws them. Server-side so the editor lists what EXISTS rather than
        # what somebody typed into a theme file.
        "cards": {"over": ["phases", "gate", "ready", "bugs"]},
        # Which group the editor keeps locked until asked twice. The palette is
        # validated for colour-vision deficiency against these very surfaces,
        # and arbitrary values make a chart two readers see differently — so the
        # unlock is a deliberate act, and the validator's verdict stays visible
        # afterwards. It is never a refusal: the user's decision, 2026-08-16.
        "locked": ["charts"],
    }


def _theme_changes(before, after):
    """Dotted change rows for a theme save, in the shape confirmChanges reads —
    the same vocabulary the config and composition saves answer in.

    EFFECTIVE values on both sides, resolved through the shipped default. A theme
    file names only what its author overrode, so the raw entry for anything else
    is absent — and reporting `from: null` for a token the reader saw a colour in
    made every first-time edit read as a mismatch against the dialog, which shows
    what is on screen. The same absence appears on the `after` side when a token
    is reverted, so both are resolved the same way.
    """
    rows = []
    defaults = _theme.DEFAULT_THEME

    def effective(entry, name, key):
        v = (entry or {}).get(key)
        if v is not None:
            return v
        d = defaults.get(name) or {}
        return d.get(key) if d.get(key) is not None else d.get("$value")

    for name in _theme.THEME_TOKENS:
        b = before.get(name) if isinstance(before, dict) else None
        a = after.get(name) if isinstance(after, dict) else None
        for mode, key in (("light", "$value"), ("dark", "$dark")):
            if name in _theme.THEME_SINGLE and mode == "dark":
                continue
            bv = effective(b, name, key)
            av = effective(a, name, key)
            if bv == av:
                continue
            rows.append({
                # `target`, the key every change row in this protocol uses and
                # the one the panel's dialog and cfTouched dereference. Both
                # sides said `scope` here, so they agreed with each other and
                # with nothing else: the dialog printed a blank target cell.
                "target": "theme",
                "field": "%s · %s" % (name, mode) if name not in _theme.THEME_SINGLE
                         else name,
                "from": bv,
                "to": av,
            })
    return rows


def _layout_changes(before, after):
    """Change rows for the non-token half — the density and the card order read
    as decisions, so they are shown as decisions rather than as JSON."""
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    rows = []
    # NORMALISED BEFORE COMPARING, not only for display. Comparing the raw values
    # made "absent" differ from "comfortable" while the row then printed both as
    # "comfortable" - a change row whose from and to were IDENTICAL, emitted
    # whenever a theme with no density was saved by a panel that sends the
    # default explicitly. Found by the differential test that holds this function
    # equal to the panel's `tLayChanges`: the panel normalises both sides, so the
    # dialog showed nothing and the save reported a row, which is exactly the
    # mismatch `appliedDiff` is there to notice.
    b_density = before.get("density") or "comfortable"
    a_density = after.get("density") or "comfortable"
    if b_density != a_density:
        rows.append({"target": "theme", "field": "layout · density",
                     "from": b_density, "to": a_density})
    bo, ao = before.get("order") or {}, after.get("order") or {}
    for view in sorted(set(list(bo) + list(ao))):
        if bo.get(view) != ao.get(view):
            rows.append({"target": "theme", "field": "layout · order · " + view,
                         "from": ", ".join(bo.get(view) or []) or "(default)",
                         "to": ", ".join(ao.get(view) or []) or "(default)"})
    return rows


def write_theme(project, body):
    """`PUT /api/theme` — write the project's theme file.

    Refused BEFORE anything is written, in the theme's own words (an unknown
    token, a value that is not a value), because a theme reaches a stylesheet
    that gets emailed and published. Contrast is reported as a WARNING and
    written anyway: how readable a reader wants their own panel is their call.

    `reset: true` deletes the file — back to the default look — rather than
    writing a theme that merely happens to equal it, so the next reader sees
    "no project theme" and not "a theme that says nothing".
    """
    if not isinstance(body, dict):
        return _not_a_json_object()
    path = os.path.join(project, ".claude", _theme.THEME_FILENAME)
    before = _theme.resolve_theme(project, read_config(project))["theme"] or {}
    if body.get("reset"):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception as exc:
            return {"ok": False, "findings": ["cannot remove %s: %s" % (path, exc)]}
        rows = _theme_changes(before, {})
        _journal(project, read_config(project), "theme.reset",
                 os.path.join(".claude", _theme.THEME_FILENAME), rows)
        return {"ok": True, "applied": rows, "reset": True,
                "warnings": [], "written": [".claude/" + _theme.THEME_FILENAME]}
    # `use` switches which theme is worn without touching any theme file: it is
    # a one-key config edit (ui.theme), written through the one config writer.
    if body.get("use") is not None:
        want = str(body.get("use") or "").strip()
        cfg = dict(read_config(project))
        ui = dict(cfg.get("ui") or {})
        if want in ("", "slate-teal"):
            ui.pop("theme", None)          # back to the search order
        else:
            ui["theme"] = want
        if ui:
            cfg["ui"] = ui
        else:
            cfg.pop("ui", None)
        return write_config(project, cfg)
    theme = body.get("theme")
    if not isinstance(theme, dict):
        return {"ok": False, "findings": ["theme must be an object of tokens"]}
    findings, warnings = _theme.validate_theme(theme)
    layout = body.get("layout")
    lf, lw = _theme.validate_layout(layout)
    findings, warnings = list(findings) + lf, list(warnings) + lw
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    rows = _theme_changes(before, theme) + _layout_changes(
        _theme.theme_layout(before), layout)
    payload = {
        "$schema": "https://design-tokens.org/schema.json",
        "$description": "audit panel/report theme — token values only; the CSS "
                        "is compiled from this and never stored.",
        "name": str(body.get("name") or "custom"),
        "tokens": theme,
    }
    if isinstance(layout, dict) and layout:
        payload["layout"] = layout
    history = body.get("history")
    if isinstance(history, list):
        # Capped where it is written, not where it is read: an unbounded trail
        # in a file somebody commits grows without anyone deciding to keep it.
        payload["history"] = history[-100:]
    save_as = str(body.get("saveAs") or "").strip()
    if save_as:
        # A named copy, and the config pointed at it: "Save as" means "keep this
        # one AND wear it", which is two writes and would be a half-done state
        # if either were skipped.
        slug = "".join(ch if (ch.isalnum() or ch in "-_") else "-"
                       for ch in save_as.lower())[:40].strip("-") or "theme"
        path = os.path.join(project, ".claude", "themes", slug + ".json")
        payload["name"] = save_as
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write_json(path, payload)
    except Exception as exc:
        return {"ok": False, "findings": ["cannot write %s: %s" % (path, exc)]}
    # Read it back through the same door every other reader uses: a file that
    # writes but does not resolve is the failure this catches.
    back, err = _theme.load_theme_file(path)
    if err:
        return {"ok": False, "findings": ["written but not readable back: %s" % err]}
    written = [_output.posix_rel(path, project)]
    if save_as:
        cfg = dict(read_config(project))
        ui = dict(cfg.get("ui") or {})
        ui["theme"] = written[0]
        cfg["ui"] = ui
        res = write_config(project, cfg)
        if not res.get("ok"):
            return res
    _journal(project, read_config(project), "theme.save", written[0], rows)
    return {"ok": True, "applied": rows, "warnings": warnings,
            "written": written, "theme": back, "savedAs": save_as or None}


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


def _apply_priority(manifest, phase, value):
    """Set or clear one phase's `priority`. Returns None, or a refusal string.

    THE RULE COMES FROM `_priority.tier_one_holder()`, WHICH IS ALSO WHAT
    `set-priority.py` ASKS. The Policy tab is the precedent: the verdict the UI
    shows is produced by the function the hook calls, so the panel cannot promise
    a write the CLI would refuse. Two places deciding what is legal are two rules,
    and the disagreement always surfaces as a save that succeeds in one surface
    and fails in the other.

    `null` is the clear — the same spelling the task `skills` opt-out uses, and
    the one a select can send for "no pin". There is no --force here on purpose:
    the panel offers the choices that are legal, and forcing a second holder of a
    unique tier is a deliberate act that belongs on a command line where the
    consequence can be typed out.
    """
    if value is None:
        phase.pop(_priority.FIELD, None)
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return ("phase %s priority must be a positive integer, or null to "
                "clear it - a tier is a rank starting at 1, and an absent "
                "priority is how a phase says 'unprioritised'"
                % (phase.get("id"),))
    if value == _priority.UNIQUE_TIER:
        others = [p for p in (manifest.get("phases") or [])
                  if isinstance(p, dict) and p is not phase]
        holder = _priority.tier_one_holder(others)
        if holder is not None:
            return ("phase %s cannot take priority %d: %s already holds it, "
                    "and that is the one tier that must be unique. Clear %s "
                    "first, or pick another tier."
                    % (phase.get("id"), _priority.UNIQUE_TIER, holder, holder))
    phase[_priority.FIELD] = value
    return None


def _apply_ado_parent(manifest, phase, value):
    """Set, clear or delete one phase's `adoParent`. None, or a refusal string.

    THREE STORED STATES AND THREE PATCH SPELLINGS, and the middle one is the
    whole reason this is not `_apply_priority` with a different field name:

      the use-fallback marker -> DELETE the key (fall through to
                                 meta.ado.parentWorkItem)
      null                    -> STORE null (hangs under nothing, on purpose)
      an object               -> STORE it, once the shape check has passed

    `null` IS THE ASYMMETRY. Every other nullable field in this patch section
    treats null as the clear, and here it is a value: pruning it would put the
    phase back under `meta.ado.parentWorkItem`, which is the exact override
    `adoParent` exists to undo, and it would do it silently - the panel would
    report a saved change that means the opposite of what was chosen. The pair
    is asserted in ONE case in `test__panel_write.py` so the difference reads as
    deliberate rather than as something discovered.

    THE SHAPE COMES FROM `_ado_parent.declaration_findings`, which is what
    `validate-manifest.py` asks - `_apply_priority`'s arrangement exactly. The
    validator runs again afterwards and would catch a bad declaration anyway;
    what refusing here buys is the message that names the field, instead of a
    wall of manifest findings about a document the operator did not type.

    `manifest` is unused and stays in the signature because every applier in
    this file takes it: `_apply_priority` needs the OTHER phases to answer its
    question, and a sibling that dropped the argument would read as if this rule
    were local when what makes it local is a fact about the rule, not about the
    call.
    """
    if _ado_parent.is_use_fallback(value):
        phase.pop(_ado_parent.FIELD, None)
        return None
    where = "phase %s" % (phase.get("id"),)
    findings, _warnings = _ado_parent.declaration_findings(
        {"id": phase.get("id"), _ado_parent.FIELD: value}, where)
    if findings:
        return "; ".join(findings)
    phase[_ado_parent.FIELD] = value
    return None


def _apply_ado_tracked(manifest, phase, value):
    """Set or clear one phase's `adoTracked`. None, or a refusal string.

    `null` IS THE CLEAR HERE, and that is the OPPOSITE of `_apply_ado_parent`
    one function up - which is why the two are written apart rather than shared.
    There, null is a value ("hangs under nothing, on purpose") and pruning it
    would silently restore the override the key exists to undo. Here the schema
    says `"type": "boolean"`, so null is not a value the field can hold and the
    key's absence is the only thing it can mean: clearing it puts the phase back
    on the default, which is TRACKED, and that is what the operator chose.

    THE SHAPE COMES FROM `_ado_tracked.declared`, which is what every other
    reader of this field asks - `_apply_ado_parent`'s arrangement exactly. It
    refuses `bool` before `int` on purpose, so `adoTracked: 1` is named as the
    typo it is rather than stored as a declaration; a refusal here says which
    field is wrong instead of handing back a wall of validator findings about a
    document the operator did not type.

    `manifest` is unused and stays in the signature for the reason it does on
    every applier in this file: `_apply_priority` needs the OTHER phases to
    answer its question, and a sibling that dropped the argument would read as
    if this rule were local when what makes it local is a fact about the rule.
    """
    if value is None:
        phase.pop(_ado_tracked.FIELD, None)
        return None
    _declared, problem = _ado_tracked.declared(
        {"id": phase.get("id"), _ado_tracked.FIELD: value})
    if problem is not None:
        return problem
    phase[_ado_tracked.FIELD] = value
    return None


def _patched_skill_names(patch):
    """Every skill name a composition patch would WRITE, deduped, in written order.

    `meta.reviewSkill` and each task's `skills` — the two places the form can put
    one. `null` and a non-string contribute nothing: the shape check downstream
    owns those, and refusing them here would give a reader the wrong reason.
    """
    out = []
    values = [(patch.get("meta") or {}).get("reviewSkill")]
    for _tid, tv in sorted((patch.get("tasks") or {}).items()):
        skills = (tv or {}).get("skills")
        values.extend(skills if isinstance(skills, list) else [])
    for value in values:
        if isinstance(value, str) and value.strip() and value.strip() not in out:
            out.append(value.strip())
    return out


def _reject_stranded(project, config, patch):
    """The refusal string when `portability` is strict and a name would not travel.

    PREVENTION AT THE POINT OF CHOICE. The doctor reports this after the fact and
    the gate can fail a build over it, but the panel is where the name is picked,
    and a defect kept out of the manifest never has to be found in it.

    Three things are deliberately NOT refused. A name discovery has never seen is
    accepted, because an inventory is not a whitelist and refusing an unknown name
    is a different feature with different consequences. A name whose verdict is
    UNKNOWN is accepted, because a refusal needs a basis and there is none. And
    everything is accepted under `warn` and `off` — the tier is what the user set,
    and a panel that ignored it would be worse than one that never had the switch.

    Fails OPEN on a scan that raises: this is a write path, and taking somebody's
    edit away because a filesystem walk failed is not a trade this makes.
    """
    modes = _config_rules.PORTABILITY_MODES
    mode = (config or {}).get("portability")
    if mode not in modes:
        mode = (getattr(_loader.load_hooks_config(), "DEFAULTS", None)
                or {}).get("portability")
    if mode != "strict":
        return None
    names = _patched_skill_names(patch)
    if not names:
        return None
    try:
        found = _panel_discovery.discover(project) or {}
    except Exception:
        return None
    have = {}
    for entry in (found.get("skills") or []):
        if isinstance(entry, dict) and entry.get("name"):
            have[entry["name"]] = entry
    bad = []
    for name in names:
        entry = have.get(name)
        if entry is not None and entry.get("travels") is False:
            bad.append("%r - %s" % (name, entry.get("travelsBasis")
                                    or "no basis was recorded"))
    if not bad:
        return None
    return ("portability is strict and %s would not survive a clone of this "
            "repository: %s. Vendor the skill under .claude/skills/, declare its "
            "plugin in the COMMITTED .claude/settings.json (both keys), or set "
            "portability to 'warn' in the Settings tab to record it anyway"
            % ("this name" if len(bad) == 1 else "these names",
               _output.some_of(bad, sep="; ")))


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
        if _priority.FIELD in (pv or {}):
            err = _apply_priority(manifest, ph, pv[_priority.FIELD])
            if err:
                return err
        if _ado_parent.FIELD in (pv or {}):
            err = _apply_ado_parent(manifest, ph, pv[_ado_parent.FIELD])
            if err:
                return err
        if _ado_tracked.FIELD in (pv or {}):
            err = _apply_ado_tracked(manifest, ph, pv[_ado_tracked.FIELD])
            if err:
                return err
        # F187. THE OTHER HALF OF `meta.areas`. The registry has had an editor
        # since areas existed, and no phase could be put IN an area afterwards -
        # `audit-task add-phase --area` writes it at creation and nothing wrote it
        # again. A registry you can curate while nothing can be assigned to it is
        # half a feature, and the half that is missing is the one every rollup,
        # every per-area total and every doctor area check reads.
        #
        # Written through `_areas.areas_of`, which is the resolution every other
        # surface already shares: it trims, drops empties and DEDUPES, and it is
        # what decides that `["api","api"]` is one tag. A second normalisation
        # here is how one phase comes to count twice in a per-area total.
        if "area" in (pv or {}):
            tags = _areas.areas_of(pv["area"])
            if not tags:
                # An emptied box is "no area", spelled by REMOVING the key: an
                # empty string or an empty list would both validate and both read
                # as "tagged with nothing", which is a different claim from
                # untagged and the one the area fallback treats as considered.
                ph.pop("area", None)
            else:
                # One tag stays a STRING, as `audit-task` writes it: the manifest
                # carries both shapes and a list of one would be a needless
                # difference between two writers of the same field.
                ph["area"] = tags[0] if len(tags) == 1 else tags
    # Same index as `_composition_changes` reads, from the same owner, so the
    # dialog's preview and the write cannot disagree about which task a patch key
    # names. An id-less task is not addressable here and never was: a JSON patch
    # key is a string, so it could never have matched the `None` this used to key.
    by_tid = _mio.tasks_by_id(manifest)
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
        # `_mio.phase_of_task` answers exactly this question and is deliberately
        # NOT used: it is LAST-wins, so on a duplicate task id it would name one
        # phase, while this needs EVERY phase holding a task by that name. The
        # answer decides which shards get written, and writing a shard that did
        # not need it costs a re-serialize; missing one loses the edit.
        for ph, t in _mio.iter_tasks(manifest):
            if t.get("id") in want:
                touched.add(ph.get("id"))
    return touched


def _write_back(project, mpath, raw_index, assembled, patch, touched,
                healed_ids=()):
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
        return [_output.posix_rel(mpath, project)]

    base = os.path.dirname(os.path.abspath(mpath))
    by_pid = {p.get("id"): p for p in (assembled.get("phases") or [])
              if isinstance(p, dict)}
    written = []
    # A phase whose patch touches ONLY index-only fields gets no shard write. Not
    # an optimisation: rewriting that shard would renormalise a file nobody edited
    # and manufacture a merge conflict against the parallel phase branch running
    # in it, for a value that does not live there.
    # `healed_ids` is subtracted because a heal is a STATUS change and status
    # lives in the shard body: a phase whose patch was priority-only but which
    # the heal also flipped still owes its shard write, and skipping it would
    # drop the heal silently.
    index_only_patch = set(
        pid for pid, pv in (patch.get("phases") or {}).items()
        if (pv or {}) and all(k in _mio.INDEX_ONLY_FIELDS for k in (pv or {}))
    ) - set(healed_ids or ())
    for stub in (raw_index.get("phases") or []):
        if not isinstance(stub, dict) or stub.get("id") not in touched:
            continue
        if stub.get("id") in index_only_patch:
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
        # ...and it never carries an index-only field either. Writing `priority`
        # here would put it exactly where `_manifest_io.index_only_in_bodies()`
        # reports it as ignored - a value the panel just promised to save, in a
        # place the next load discards.
        for k in _mio.INDEX_ONLY_FIELDS:
            body.pop(k, None)
        _atomic_write_json(spath, body)
        written.append(_output.posix_rel(spath, project))

    # The INDEX is written for `meta`, and for any index-only field a phase patch
    # touched. Those two are separate reasons and both are needed: a priority
    # written only into the shard would vanish on the next load, and a save that
    # rewrote the index for every phase edit would renormalise a file nobody
    # touched - the merge conflicts the targeted write-back exists to avoid.
    index_only_touched = sorted(
        pid for pid, pv in (patch.get("phases") or {}).items()
        if any(k in (pv or {}) for k in _mio.INDEX_ONLY_FIELDS))
    if patch.get("meta") or index_only_touched:
        idx = dict(raw_index)
        if patch.get("meta"):
            idx["meta"] = assembled.get("meta") or {}
        if index_only_touched:
            idx["phases"] = [_index_only_stub(entry, by_pid)
                             for entry in (raw_index.get("phases") or [])]
        _atomic_write_json(mpath, idx)
        written.append(_output.posix_rel(mpath, project))
    return written


def _index_only_stub(entry, by_pid):
    """One index entry with its index-only fields taken from the patched phase.

    A NEW dict per entry rather than a mutation of `raw_index`: the caller reads
    `raw_index` again after the write (and `_write_back` is called inside a lock
    whose failure path restores from disk), so editing it in place would leave a
    half-applied index in memory behind a write that raised.
    """
    if not isinstance(entry, dict):
        return entry
    patched = by_pid.get(entry.get("id"))
    if not isinstance(patched, dict):
        return entry
    out = dict(entry)
    for k in _mio.INDEX_ONLY_FIELDS:
        if k in patched:
            out[k] = patched[k]
        else:
            out.pop(k, None)
    return out


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
    err = _reject_stranded(project, config, patch)
    if err:
        return {"ok": False, "findings": ["refused: " + err]}
    err = apply_composition_patch(assembled, patch)
    if err:
        return {"ok": False, "findings": ["refused: " + err]}
    # The heal rides a real write only (`applied` non-empty): an unchanged
    # save writes no file for it to ride, and the validator warning still
    # names the state for the reader. Validated AFTER healing -- the document
    # judged is the document written.
    healed = _heal_phase_status(assembled) if applied else []
    findings, warnings = vm.validate(assembled)
    # The browser joins these into ONE sentence with a separator (`core.js`
    # renderResult), so a rule that fires once per task arrives there as a
    # paragraph saying one thing nineteen times - the panel's own comment about
    # `staleNote` says why that reads as nineteen problems. `findings` is left
    # alone: it refuses the save, and a refusal is read item by item.
    warnings = _wg.collapse(warnings, assembled)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    if not applied:
        # A patch whose every field already holds the value it asks for. Writing it
        # would rewrite shards nobody edited — the exact renormalisation the
        # targeted write-back exists to avoid — to record no change at all.
        return {"ok": True, "findings": [], "warnings": warnings, "applied": [],
                "healed": [], "unchanged": True, "journaled": False,
                "journaledWhy": "unchanged", "written": [],
                "path": _output.posix_rel(mpath, project),
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
        written = _write_back(project, mpath, raw_index, assembled, patch,
                              touched, [r["target"] for r in healed])
    except ValueError as exc:
        return {"ok": False, "findings": [str(exc)]}
    finally:
        _release_write_lock(lock)
    out = {"ok": True, "findings": [], "warnings": warnings, "applied": applied,
           "healed": healed,
           "path": _output.posix_rel(mpath, project),
           "layout": "sharded" if sharded else "single",
           "written": written}
    out.update(_journal(project, config, "composition.write",
                        out["path"], applied + healed))
    return out


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_write.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__panel_write.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
