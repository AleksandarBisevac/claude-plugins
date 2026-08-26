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

import _journal_io            # noqa: E402  (repo_relative_or_token: the redactor, at layer 1)
import _locks                 # noqa: E402  (lock paths + the liveness verdict, at layer 1)
import _evidence_io as _ev    # noqa: E402  (where the test-run ledger lives, at layer 2)
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
    names, then the newest (mtime_ns, size) across the ledger dir's *.jsonl,
    then the same across the EVIDENCE dir's. Pure stats per request — no watcher
    thread, no state between calls — folded into /api/runstatus so the existing
    5s poll carries it for free.

    THE EVIDENCE DIRECTORY IS STAMPED FOR THE SAME REASON AS THE LEDGER, and it
    is the half a live panel is actually for: a gate that finishes mid-phase
    appends a row there and moves a pointer in the manifest, and the pointer's
    shard is already watched — but a `--reconcile` pass, or a run recorded while
    another session held the phase lock, writes the row and NOT the shard. Watch
    the manifest alone and that badge waits for a manual reload.

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

    def newest_jsonl(directory):
        """The newest (mtime_ns, size) across a directory's *.jsonl, as a stamp.

        ONE EXPRESSION FOR TWO DIRECTORIES. The usage ledger and the evidence
        ledger are the same shape — append-only *.jsonl, one file per writer per
        month — and a second copy of this loop is a second chance for one of them
        to quietly stop being watched, which is precisely the failure the stamp
        exists to prevent. "-" for a directory that is missing, unreadable, or
        holds no *.jsonl, so a project with no ledger yet yields a STABLE
        sentinel rather than a stamp that moves on nothing.
        """
        newest = None
        try:
            for name in os.listdir(directory):
                if name.endswith(".jsonl"):
                    st = os.stat(os.path.join(directory, name))
                    key = (st.st_mtime_ns, st.st_size)
                    if newest is None or key > newest:
                        newest = key
        except Exception:
            newest = None
        return "-" if newest is None else "%d:%d" % newest

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
        try:
            parts.append(newest_jsonl(
                str(_paths.hooks_config().ledger_dir(project, config))))
        except Exception:
            # The directory RESOLUTION is what can raise here; the walk cannot.
            # Same sentinel either way, so a project whose ledgerDir cannot be
            # resolved stamps stably instead of moving the fingerprint on every
            # poll.
            parts.append("-")
        try:
            parts.append(newest_jsonl(_ev.evidence_dir(project, config)))
        except Exception:
            parts.append("-")
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return "unavailable"


# --- what a feed row may say once it leaves the machine ---------------------------
def _redacted_event(project, row):
    """One gate-events row with its `file` cell put through the journal's redactor.

    `audit-logs.py prune` counts an out-of-repository row by CLASS and never echoes
    its path, on the argument that the path is the thing being removed and printing
    it would put it back. This card renders the same rows, and it was giving the
    opposite answer: the user name, the temp root and the session slug of whoever
    ran the gate, painted verbatim into a card `docs/screenshots/panel-gate.png` is
    a committed render of - and `tools/check-committed-pii.py` cannot read a PNG.
    Redacted HERE rather than in the browser, so the path never reaches the page.

    `_journal_io.repo_relative_or_token` is the rule, not a second one written to
    resemble it: the same function every committed journal row goes through, with
    the same failure direction - anything unresolvable, empty or outside becomes
    the token, because a guess that leaks is worse than a cell that says less.

    NOT quite the same verdict as `_gate_feed.classify`, and the difference is the
    failure direction rather than an inconsistency: that one asks `within_root`,
    which answers *inside* for a path it cannot resolve because a gate must not
    move on a guess, while this one lands every such tie on the token because a
    surface must not paint on one. So this card can only ever say LESS about a row
    than the prune would keep - never more, which is the only direction that is
    safe here.

    ONLY `file` is rewritten. The other keys `append_gate_event` allows are a
    verdict word, a tier word, a session id, and a `reason` that is either a fixed
    sentence or a hook message's first line - so a path in one of those is a leak
    at the WRITER, and rewriting it here would only hide it from this one card.

    An absent or blank `file` is returned untouched: that cell renders empty today,
    and stamping the token onto it would claim a path the row never named.
    """
    if not isinstance(row, dict):
        return row
    named = row.get("file")
    if not (isinstance(named, str) and named.strip()):
        return row
    shown = dict(row)
    shown["file"] = _journal_io.repo_relative_or_token(project, named.strip())
    return shown


def _gate_block(project, config):
    """The Plan gate card's payload (v0.34 B3): tier + why, whether a bypass is
    armed, and the tail of the gate events feed.

    Computed SERVER-SIDE with the hooks' own functions (`plan_gate_mode`,
    `plan_gate_knob`, `manifest_state` through `_cores()[3]`), so the card can
    never disagree with the gate about what tier is in force — the same rule
    the policy switchboard follows. Events are the newest ~20 lines of
    `<logsDir>/plan-gate-events.jsonl`, newest first, each row's `file` cell
    through `_redacted_event` so a path outside the repository leaves as its
    class and not as itself; the armed indicator honours the same TTL
    require-plan honours, so the card never claims a bypass the gate would
    refuse. Never raises; a bare dict on any miss."""
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
                    out["events"].append(_redacted_event(project, row))
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
