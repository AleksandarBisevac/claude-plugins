#!/usr/bin/env python3
"""
Who is running what, right now: the shared git-dir locks and their liveness,
the on-disk change stamp the panel's poll watches, and the Plan gate card.

Split out of `_panel_state.py` (U3.1). Layer 4, above `_panel_paths` (3);
`_locks` at 1 is its only other reach.

Stdlib only, Python 3.8 compatible.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

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

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _locks                 # noqa: E402  (lock paths + the liveness verdict, at layer 1)
import _panel_paths as _paths  # noqa: E402  (the shared base, at layer 3)

# Carried by module-level alias so every body below reads exactly as it did in
# `_panel_state`, where these were siblings rather than imports.
_config_path = _paths._config_path
_manifest_path = _paths._manifest_path
_read_json = _paths._read_json
read_config = _paths.read_config


# --- concurrency-lock detection (locks live in the shared git dir, not the tree) --
_LOCKDIR_CACHE = {}


def _audit_lock_dir(project, config):
    """The shared audit-locks dir: $(git -C <gitRoot> rev-parse --git-common-dir)/audit-locks
    — where the orchestrator now keeps its index + per-phase locks (out of the working tree,
    shared across worktrees). None when this isn't a git repo (caller falls back to the legacy
    working-tree lock). Cached per git-root: build_state runs per request; the git dir never moves."""
    git_root = os.path.realpath(os.path.join(project, (config or {}).get("gitRoot") or "."))
    if git_root in _LOCKDIR_CACHE:
        return _LOCKDIR_CACHE[git_root]
    lockdir = None
    try:
        out = subprocess.run(["git", "-C", git_root, "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            gd = out.stdout.strip()
            if not os.path.isabs(gd):
                gd = os.path.join(git_root, gd)
            lockdir = os.path.join(os.path.realpath(gd), "audit-locks")
    except Exception:
        lockdir = None
    _LOCKDIR_CACHE[git_root] = lockdir
    return lockdir


def _audit_lock_held(project, config):
    """True iff any /audit run holds a lock — the index lock OR any per-phase-shard lock.
    Checks the shared git-dir lock dir, falling back to the legacy working-tree lock, so the
    panel's 'locked' signal (and its composition-write refusal) keeps working in both layouts."""
    lockdir = _audit_lock_dir(project, config)
    if lockdir and os.path.isdir(lockdir):
        try:
            for name in os.listdir(lockdir):
                if name == "index.lock" or (name.startswith("phase-") and name.endswith(".lock")):
                    return True
        except Exception:
            pass
    return os.path.exists(_manifest_path(project, config) + ".lock")   # legacy fallback


def _lockmod():
    """`_locks`, the lock's read side — where one lives and whether it is live.

    A plain import at layer 1 now, not a `_loader.load_script("audit-lock.py")`:
    this module is layer 5 and that was an entry point, one of the edges
    `_deps.KNOWN_LAYER_DEBT` recorded. Kept as a function returning a module,
    with the None contract intact, because `_lock_info` below reads `None` as
    "show the lock without a liveness verdict rather than show nothing" — and an
    import that cannot fail is not a reason to delete a caller's fallback."""
    return _locks


def _lock_info(lockdir):
    """Read the shared audit-locks dir into {'index': info|None, 'phases': {pid: info}}.

    Each info is the lock file's `{hostname, startedAt, note}` (or {} if unreadable),
    plus `live` and `liveBasis` from audit-lock.py. The panel used to badge every
    lock file "running", which is a claim about a process it had not checked — an
    abandoned lock and a working one looked identical, and the badge was most
    confident exactly when it was most likely wrong.
    """
    out = {"index": None, "phases": {}}
    if not (lockdir and os.path.isdir(lockdir)):
        return out
    try:
        names = os.listdir(lockdir)
    except Exception:
        return out
    lock = _lockmod()
    for name in names:
        if not name.endswith(".lock"):
            continue
        path = os.path.join(lockdir, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                info = json.load(fh)
        except Exception:
            info = {}
        if not isinstance(info, dict):
            info = {}
        if lock is not None:
            try:
                info["live"], info["liveBasis"] = lock.judge(info, path)
            except Exception:
                pass
        if name == "index.lock":
            out["index"] = info
        elif name.startswith("phase-"):
            out["phases"][name[len("phase-"):-len(".lock")]] = info
    return out


def data_fingerprint(project, config):
    """A cheap change stamp over everything the panel renders from disk (lv).

    (mtime_ns, size) of: the CONFIG file first (manifestPath/ledgerDir live in
    it, so a config edit must move the stamp even when it merely points the
    panel at different files), then the manifest, then every shard the index
    names, then the newest (mtime_ns, size) across the ledger dir's *.jsonl.
    Pure stats per request — no watcher thread, no state between calls —
    folded into /api/runstatus so the existing 5s poll carries it for free.

    SSE was weighed and rejected for this: through the stdlib server it would
    be stream-until-close over HTTP/1.0 (no chunked replies), a second send
    path beside _send, and one parked thread per open tab — for a localhost
    tool whose staleness budget the poll already meets.

    A missing file stamps as "-", so a project with nothing on disk yields a
    STABLE sentinel rather than an error; this function never raises.
    """
    def stamp(path):
        try:
            st = os.stat(path)
            return "%d:%d" % (st.st_mtime_ns, st.st_size)
        except Exception:
            return "-"

    parts = []
    try:
        parts.append(stamp(_config_path(project)))
        mpath = _manifest_path(project, config)
        parts.append(stamp(mpath))
        try:
            idx = _read_json(mpath)
        except Exception:
            idx = None
        if isinstance(idx, dict):
            base = os.path.dirname(os.path.abspath(mpath))
            for ph in idx.get("phases") or []:
                if isinstance(ph, dict) and isinstance(ph.get("shard"), str):
                    parts.append(stamp(os.path.join(base, ph["shard"])))
        newest = None
        try:
            led = str(_paths.hooks_config().ledger_dir(project, config))
            for name in os.listdir(led):
                if name.endswith(".jsonl"):
                    st = os.stat(os.path.join(led, name))
                    key = (st.st_mtime_ns, st.st_size)
                    if newest is None or key > newest:
                        newest = key
        except Exception:
            newest = None
        parts.append("-" if newest is None else "%d:%d" % newest)
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return "unavailable"


def _gate_block(project, config):
    """The Plan gate card's payload (v0.34 B3): tier + why, whether a bypass is
    armed, and the tail of the gate events feed.

    Computed SERVER-SIDE with the hooks' own functions (`plan_gate_mode`,
    `plan_gate_knob`, `manifest_state` through `_cores()[3]`), so the card can
    never disagree with the gate about what tier is in force — the same rule
    the policy switchboard follows. Events are the newest ~20 lines of
    `<logsDir>/plan-gate-events.jsonl`, newest first; the armed indicator
    honours the same TTL require-plan honours, so the card never claims a
    bypass the gate would refuse. Never raises; a bare dict on any miss."""
    out = {"mode": "observe", "source": "", "bypassArmed": False, "events": []}
    try:
        cfg_mod = _paths.hooks_config()
        config = config if isinstance(config, dict) else {}
        manifest_rel = (config.get("manifestPath")
                        or cfg_mod.DEFAULTS["manifestPath"])
        state = cfg_mod.manifest_state(project, manifest_rel)
        out["mode"] = cfg_mod.plan_gate_mode(config, state)
        knob = cfg_mod.plan_gate_knob(config)
        if knob:
            out["source"] = ("planGate: \"%s\" in .claude/audit.config.json "
                             "(pinned)" % knob)
        elif cfg_mod.enforce_always(config):
            out["source"] = ("enforce: true (legacy; same as planGate: "
                             "\"deny\")")
        elif not state.get("exists"):
            out["source"] = "graded on evidence: no manifest at %s" % manifest_rel
        elif state.get("phaseRunning"):
            out["source"] = ("graded on evidence: phase %s is in_progress"
                             % state.get("runningPhase"))
        else:
            out["source"] = ("graded on evidence: manifest present, nothing "
                             "running")
        sd = os.path.join(str(project),
                          str(config.get("stateDir")
                              or cfg_mod.DEFAULTS["stateDir"]))
        try:
            for name in os.listdir(sd):
                if not (name.startswith("plan-bypass-")
                        and name.endswith(".json")):
                    continue
                try:
                    with open(os.path.join(sd, name), "r",
                              encoding="utf-8") as fh:
                        info = json.load(fh) or {}
                    at = (info.get("armedAtEpoch")
                          if isinstance(info, dict) else None)
                    if (isinstance(at, (int, float))
                            and not isinstance(at, bool)
                            and time.time() - at > cfg_mod.BYPASS_TTL_SECONDS):
                        continue          # expired: require-plan would refuse it
                except Exception:
                    pass                  # unreadable = legacy shape = armed
                out["bypassArmed"] = True
                break
        except Exception:
            pass
        try:
            feed = os.path.join(str(project),
                                str(config.get("logsDir")
                                    or cfg_mod.DEFAULTS["logsDir"]),
                                cfg_mod.GATE_EVENTS_FILE)
            with open(feed, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            for line in reversed(lines[-20:]):        # newest first
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    out["events"].append(row)
        except Exception:
            pass
    except Exception:
        pass
    return out


def _run_status(project, config, manifest):
    """Per-phase live run status for the panel ('who's running what'): which phase is
    locked (and by whom) and which carries an optimistic claim. Combines the shared
    git-dir phase locks with each phase's `claim` from the manifest.

    Also carries `fingerprint` (data_fingerprint above): the poll that reads this
    endpoint is how the panel notices the files moved on disk — a fingerprint
    change hands off to refreshFromDisk instead of repainting Overview. And the
    `gate` block (v0.34 B3): the Plan gate card's tier/source/bypass/events,
    which DOES enter the client's `runStatusKey` ({index, phases, gate}), so a
    fresh gate event repaints the card without the poll ever refetching full
    state (the D9 rule, still literally true of the poll itself)."""
    locks = _lock_info(_audit_lock_dir(project, config))
    phases = {}
    if isinstance(manifest, dict):
        for p in manifest.get("phases", []) or []:
            if isinstance(p, dict) and p.get("id"):
                claim = p.get("claim")
                phases[p["id"]] = {
                    "lock": locks["phases"].get(p["id"]),
                    "claim": claim if isinstance(claim, dict) else None}
    for pid, info in locks["phases"].items():          # locks for phases not in the manifest
        phases.setdefault(pid, {"lock": info, "claim": None})
    return {"index": locks["index"], "phases": phases,
            "fingerprint": data_fingerprint(project, config),
            "gate": _gate_block(project, config)}


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_runstate.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__panel_runstate.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
