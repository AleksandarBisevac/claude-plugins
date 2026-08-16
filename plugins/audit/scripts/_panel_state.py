#!/usr/bin/env python3
"""
The panel's READ side: everything `GET /api/*` answers with, off panel-server.py.

Moved out of panel-server.py (P12.3). Nothing here writes: given a project
directory it reads the config, the manifest (single-file OR sharded), the usage
ledger, the audit locks, the journal and the capability policy, and returns the
JSON payloads the UI renders -- `build_state`, `areas_state`, `policy_state`,
`journal_state`, `usage_state`, `help_state`, plus the report export whose only
side effect is the report file the renderer itself writes.

Where this module sits: ABOVE _loader / _manifest_io / _help / _areas / _policy /
_panel_settings / _panel_discovery, and BELOW panel-server (and, from P12.4, the
write path). It must never import panel-server -- a selftest case below says so.

panel-server.py keeps a thin module-level alias for every name moved here, so its
HTTP routes, its write path and its own selftest keep referring to them unchanged.

BOUNDARY DECISIONS -- read-side code that touched names the write path also uses:

  * `_load` / `_cores` / `_defaults`. `_cores` is called from both sides
    (`build_state`, `_viewer`, `usage_state`, `_policy_enforcement` here;
    `write_config` and `apply_composition` there). It MOVED and panel-server
    aliases it back, rather than each module keeping its own copy: `_VM/_VC/_AS/
    _CFG` is a memo, and two memos would mean two `_cores()` first-calls and two
    answers to "have the cores been loaded yet" -- harmless today only because
    `_loader` caches underneath, and exactly the kind of split state that stops
    being harmless the moment a selftest patches one of them.

  * `_read_json`. Moved (it is what `read_config` reads through) and aliased back
    for the write path's index read. Its twin `_atomic_write_json` STAYS in
    panel-server: nothing here writes JSON, and the selftest below goes through
    `_mio.atomic_write_json` directly for its fixtures.

  * `_JOURNAL` / `_journalmod`. The journal WRITER (`_journal`) stays in
    panel-server (P12.4), but `journal_state` needs the same module handle, so the
    loader and its one-shot memo moved here and are aliased back. The alias is the
    same dict object, so the selftest cases on both sides that swap a stub module
    in by mutating `_JOURNAL` in place still reach one shared piece of state.

  * `_active_area_tags` moved with `policy_state`, its only caller.

  * `discover` is used by `policy_state` and reached here as
    `_panel_discovery.discover` -- panel-server's own alias is for its
    /api/registry route, not something this module reads back out of it.

Stdlib only, Python 3.8 compatible.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_REL = ".claude/audit.config.json"

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (meta.areas registry + shared resolution)
import _policy                # noqa: E402  (the capability policy + its resolution)
import _help                  # noqa: E402  (schema-sourced field help + concept topics)
import _loader                # noqa: E402  (the one path-importlib loader for scripts/)
import _panel_discovery       # noqa: E402  (skills/agents/MCP registry scan)

discover = _panel_discovery.discover


def _src_of_this_file():
    """This module's own source -- for the selftests that must assert a server-side
    construct (a call order, a shipped field) rather than a rendered string."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


# --- lazy import of the plugin's own pure cores (hyphenated filenames) ----------
def _load(modname, path):
    """Thin per-call wrapper: callers here pass an explicit modname (the file is
    hyphenated and not otherwise importable). Delegates to `_loader`, the one
    shared path-importlib loader — see its docstring for the caching policy."""
    return _loader.load(path, modname=modname)


_VM = _VC = _AS = _CFG = None


def _cores():
    """Load (once) validate-manifest, validate-config, audit-status, _config."""
    global _VM, _VC, _AS, _CFG
    if _VM is None:
        _VM = _loader.load_script("validate-manifest.py",
                                   modname="audit_validate_manifest")
        _VC = _loader.load_script("validate-config.py",
                                   modname="audit_validate_config")
        _AS = _loader.load_script("audit-status.py", modname="audit_status")
        _CFG = _loader.load_hooks_config(modname="audit__config")
    return _VM, _VC, _AS, _CFG


def _defaults():
    return _cores()[3].DEFAULTS


# --- path safety ----------------------------------------------------------------
def _within(project, path):
    """True iff `path` resolves inside `project` (no ../ escape, no symlink out)."""
    proj = os.path.realpath(project)
    tgt = os.path.realpath(path)
    return tgt == proj or tgt.startswith(proj + os.sep)


def _config_path(project):
    return os.path.join(project, CONFIG_REL)


def _declared_as_of(config):
    """Did the PROJECT set `usage.pricingAsOf`, or is the effective value a default?

    `usage_cfg()` merges `DEFAULTS`, so `ucfg["pricingAsOf"]` is almost never absent
    — it falls back to the default table's date. Rendering that as the rate basis
    would present a date this project never chose as though it had, which is the
    manufactured basis `render-report._usage_context` refuses for the same reason.
    The panel needs the raw config to tell the two apart, so it reports the fact
    separately rather than making the client guess from a value that is always set.
    """
    block = (config or {}).get("usage")
    return isinstance(block, dict) and isinstance(block.get("pricingAsOf"), str) \
        and bool(block["pricingAsOf"].strip())


def _manifest_path(project, config):
    mp = (config or {}).get("manifestPath") or _defaults()["manifestPath"]
    return os.path.normpath(os.path.join(project, mp))


# --- who is looking at this panel -------------------------------------------------
# {(project, mode): {"watch": [...], "stamp": [...], "env": [...], "viewer": {...}}}.
# One entry per (project, mode): panel-server serves exactly one project, and the
# CLI callers (audit-task through _panel_write) run once and exit — so this is not
# a growth surface worth bounding.
#
# panel-server is a ThreadingHTTPServer, so two requests can be in here at once.
# That is safe under one rule: an entry is REPLACED, never edited in place. A
# reader holds the whole entry it fetched, so a concurrent writer swapping in a new
# one cannot tear the stamp away from the watch list it belongs to. The worst
# outcome is a redundant resolve. Do not "optimize" this by mutating the hit. Same
# rule, same reason, as `_panel_discovery._DISCOVERY_CACHE`.
_VIEWER_CACHE = {}

# The validity token and the settle rule are `_panel_discovery`'s, by REFERENCE and
# not by copy: both caches guard the same class of thing — a file a human edits by
# hand, on filesystems whose mtime is often 1-second granular — and two
# implementations of "has anything moved" is two answers to it. See `_stamp` there
# for why size and inode ride along with mtime, and `_SETTLE_SECONDS` for the race
# a same-second write opens.
_stamp = _panel_discovery._stamp
_settled = _panel_discovery._settled

# The non-`GIT_CONFIG*` half of the environment the answer moves with: HOME and
# XDG_CONFIG_HOME decide WHERE the global config is, and USER/USERNAME ARE the
# answer when git has no identity to give.
_IDENTITY_ENV = ("HOME", "XDG_CONFIG_HOME", "USER", "USERNAME")


def _identity_env():
    """The environment `resolve_author` reads, as sorted `(name, value)` pairs.

    Every `GIT_CONFIG*` variable, because that family decides which files git opens
    at all (`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM`) and can
    carry the config with no file involved (`GIT_CONFIG_COUNT` plus
    `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n`) — matched by PREFIX rather than listed,
    so a variable a later git adds to that family is covered without this file being
    edited. Pinned by value: none of these moves any file's mtime, so no stat could
    ever see one change.
    """
    return sorted((k, v) for k, v in os.environ.items()
                  if k.startswith("GIT_CONFIG") or k in _IDENTITY_ENV)


def _git_config_origins(project):
    """The config files git ITSELF says it read for `project` — absolute ones only.

    Asked of git rather than reconstructed from its documented search order, because
    that order is not something this file can hold honestly: the system config lives
    wherever the build put it (on the machine this was written on, inside Xcode.app
    rather than /etc/gitconfig), and `includeIf "gitdir:…"` — the standard way to
    carry a second `user.email` for one tree — pulls in a path nothing here could
    predict. A config file that decides the identity and is not watched is exactly
    the stale answer this cache exists to have stopped having.

    `--name-only` is not a nicety. A plain `--list` also hands back every VALUE, and
    a git config routinely holds credential helpers and tokens; only the paths are
    wanted here, so only the paths are read.

    A RELATIVE origin (git spells the repo config `file:.git/config`) is dropped: it
    is relative to the repository top-level, not to `project`, and
    `_git_config_candidates` already stamps that same file from `project` and every
    ancestor — which is where it sits when `project` is a subdirectory.
    """
    try:
        res = subprocess.run(["git", "-C", str(project), "config", "--list",
                              "--show-origin", "--name-only"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5)
        text = (res.stdout or b"").decode("utf-8", "replace")
    except Exception:
        text = ""
    out = []
    for line in text.splitlines():
        if not line.startswith("file:"):
            continue
        path = line[len("file:"):].split("\t", 1)[0]
        if os.path.isabs(path):
            out.append(path)
    return out


def _git_config_candidates(project):
    """The config files that do NOT exist yet but would decide the answer if one
    appeared.

    The half a token built only from what was READ cannot have, and the half that
    matters: `git config --global user.email` on a machine with no `~/.gitconfig`
    writes a file the previous resolve never opened. `_stamp` records an absent path
    as absent rather than dropping it, so one appearing is a mismatch.

    Walking UP from `project` rather than testing it alone: `resolve_author` runs
    `git -C project`, and git searches upward for the repository, so a `.git` created
    anywhere above `project` is a place a repo-local identity can appear.
    """
    home = os.environ.get("HOME") or os.path.expanduser("~")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    out = [os.environ.get("GIT_CONFIG_GLOBAL") or os.path.join(home, ".gitconfig"),
           os.path.join(xdg, "git", "config"),
           os.environ.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig"]
    seen = set()
    node = os.path.realpath(project)
    while node not in seen:
        seen.add(node)
        out.append(os.path.join(node, ".git", "config"))
        out.append(os.path.join(node, ".git", "config.worktree"))
        node = os.path.dirname(node)
    return out


def _resolve_viewer(project, mode):
    """One uncached resolve: `({author, mode}, watched_paths)`.

    Split out so the cache has a seam to wrap, and so the watch list is produced BY
    the resolve rather than guessed alongside it — `_panel_discovery._discover_scan`
    's shape, for the reason stated there: a watch list maintained apart from the
    read it describes drifts from it, and a drifted watch list is a cache that goes
    stale in silence.

    `mode: none` is deliberately NOT special-cased into an empty watch list, even
    though `resolve_author` returns before reading anything in that mode: knowing
    that here would be a second implementation of a rule that function owns, and the
    two would eventually disagree. Over-watching costs a resolve; under-watching
    costs a wrong name.
    """
    author = None
    try:
        ul = _loader.load_script("usage_ledger.py", modname="audit_usage_ledger")
        author = ul.resolve_author(project, mode)
    except Exception:
        author = None
    return ({"author": author, "mode": mode},
            _git_config_origins(project) + _git_config_candidates(project))


def _viewer(project, config):
    """Who is driving the panel: `{author, mode}`.

    Resolved by `usage_ledger.resolve_author` — the SAME function, reading the same
    `usage.authorMode` — rather than by asking git here. The two names have to be
    one string: the Usage tab offers a "my spend" filter that compares this value
    with the `author` column the ledger writes, and a second implementation would
    produce a filter that matches nothing on any project where the two disagreed
    (mode `hash`, say, or a repo-local `user.email`).

    `mode: none` is a real answer, not a failure: it means this project chose not
    to record who spent what, and the panel says so rather than inventing a name.

    WHY THERE IS A CACHE. `resolve_author` shells out to git (up to two
    `git config --get` runs) and `build_state` calls this on EVERY `/api/state`.

    INVALIDATION — the whole design, so it is stated rather than implied. This
    cache had none: keyed on `(project, mode)` and populated once, it never expired
    and was never invalidated, so `git config user.email` changed against a panel
    that had been up for hours kept answering with the old identity, and the Usage
    tab's "my spend" filter silently selected the wrong rows. A stale answer is
    worse than a slow one here — reflecting what is on disk is this panel's job.

      * The token is a fresh `os.stat` of every file that can decide the answer:
        every ABSOLUTE origin `git config --list --show-origin` reports for this
        project (system, global, XDG, and whatever an `include`/`includeIf` pulled
        in), plus the repo config of `project` and of each ancestor, plus the
        global and system locations that do not exist yet. Absent paths are stamped
        as absent, so `git config --global user.email` on a machine with no
        `~/.gitconfig` invalidates by CREATING one of them — the case a token built
        only from what was read gets wrong.
      * Plus the environment, BY VALUE (`_identity_env`): `GIT_CONFIG_*` decides
        which files git opens and can carry the config with no file involved,
        `HOME`/`XDG_CONFIG_HOME` decide where the global one lives, and
        `USER`/`USERNAME` IS the answer when git has no identity to give. None of
        those moves a file's mtime, so no stat could see them.
      * `mode` stays in the KEY, not the token: it is read out of the project's own
        `.claude/audit.config.json`, which `build_state` re-reads per request, so a
        changed `usage.authorMode` arrives here as a different key already.
      * It is NOT a TTL. A TTL has a window in which the panel knowingly shows the
        wrong person's name, and a window short enough to be honest is short enough
        that the cache buys nothing. Measured on this repo on one developer
        machine: 16 watched paths, revalidated in 0.05 ms, against the 30 ms the
        resolve costs (module load plus up to three `git config` runs). Statting
        more paths than a TTL would is the price of the token being honest, and it
        is still the cheaper half by 600x.
      * A resolve whose files were being written AS it ran is returned but not
        cached (`_settled`): mtime is 1-second granular on plenty of filesystems,
        so an edit landing in the same second as the read can be stamped under an
        mtime the token already holds — after which the pre-edit name would be
        served forever, which is the original bug wearing a smaller window.
        Refusing to cache is the safe direction: the caller still gets the right
        answer, it just costs a resolve.

    `_panel_discovery.discover`'s docstring cites this cache as the codebase's
    cautionary never-invalidating case. That citation is now historical and wants a
    one-line correction there.
    """
    _, _, _, cfg_mod = _cores()
    mode = str((cfg_mod.usage_cfg(config) or {}).get("authorMode") or "email")
    key = (os.path.realpath(project), mode)
    env = _identity_env()
    hit = _VIEWER_CACHE.get(key)
    if hit is not None and hit["env"] == env \
            and _stamp(hit["watch"]) == hit["stamp"]:
        return dict(hit["viewer"])
    started = time.time()
    viewer, watch = _resolve_viewer(project, mode)
    watch = sorted(set(watch))
    stamp = _stamp(watch)
    if _settled(stamp, started):
        _VIEWER_CACHE[key] = {"watch": watch, "stamp": stamp, "env": env,
                              "viewer": viewer}
    else:
        # Not merely "do not store": an entry from an earlier, settled resolve
        # would still be serving its own answer, and this resolve just saw an
        # identity file move.
        _VIEWER_CACHE.pop(key, None)
    # A copy, always — the cached dict outlives the request, and one caller writing
    # to the payload it was handed would corrupt the next caller's answer with
    # nothing raised anywhere.
    return dict(viewer)

def _read_json(path):
    """Thin delegation to the plugin's ONE JSON reader (_manifest_io.read_json)."""
    return _mio.read_json(path)

# --- state (read) ---------------------------------------------------------------
def read_config(project):
    try:
        obj = _read_json(_config_path(project))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

# A phase's `area` -> its tags. One implementation, in `_areas`, shared with
# audit-status: this file and that one each had their own copy of the same six
# lines, and the day one of them learned something (trimming, de-duplication, the
# registry lookup) the panel and the terminal would have disagreed about which
# phases are in an area.
_areas_of = _areas.areas_of

def _bugs_view(manifest):
    """The bug rows the Overview lists, one per bug, already resolved.

    `status` here is the EFFECTIVE status — the same value `rollup()` counts in
    `bugs.byStatus`, computed by the same function — so a reader who clicks the
    "Fixed 2" pill gets exactly two rows. Deriving it a second time in JavaScript
    would be a second implementation of the bug<->task rule (a bug materialized
    into a task reads `fixed` once that task is done), and two implementations
    that can disagree is precisely how the panel's counts and its lists drift.
    `reported` keeps what the manifest actually stores, so a bug whose status is
    inherited from its task can say so instead of looking hand-edited."""
    _, _, as_, _ = _cores()
    # The two indexes come from `_manifest_io` — the module that owns the shape —
    # rather than from a walk here; `phase_of_task` is why the enclosing `phases`
    # list this used to build is gone, since nothing else needed the phase bodies.
    # They are guaranteed to share a key set, which is what lets a row read both.
    task_by_id = _mio.tasks_by_id(manifest)
    task_phase = _mio.phase_of_task(manifest)
    out = []
    for b in (manifest.get("bugs") or []):
        if not isinstance(b, dict):
            continue
        eff = _mio.effective_bug_status(b, task_by_id)
        out.append({
            "id": b.get("id"), "title": b.get("title"),
            "status": eff,
            "reported": b.get("status"),
            "severity": b.get("severity"),
            # `open` and `high` are decided HERE, by the same two rules the rollup's
            # `open` / `openHighSeverity` counts use — CLOSED_BUG and the
            # high-or-worse severity set, which knows that critical, blocker, sev1
            # and p0 all mean high. A regex in the browser would be a third opinion
            # on the same question, and the "High severity, open" pill would
            # eventually count a different set than the list it filters to.
            "open": eff not in as_.CLOSED_BUG,
            "high": as_._is_high_severity(b.get("severity")),
            "taskId": b.get("taskId"),
            "phaseId": task_phase.get(b.get("taskId")),
            "reportedAt": b.get("reportedAt"),
        })
    return out


def _skills_of(task):
    """A task's skills as the panel SHOWS them — the THREE states kept apart.

    Explicit `null` is a conscious opt-out ("none applies" — it stops the area
    fallback, v0.37 B1) and stays None, so every display can say so instead of
    rendering it as empty. `[]` and an absent key both mean "unconsidered" and
    read as []; a junk-typed value reads as [] too (the validator names it).
    This is also the value a change row is written against: the client's form
    holds the same three states, so `[] -> [a]` and `null -> [a]` stay two
    different edits rather than a normalisation disagreement — which is the
    original reason this normaliser exists.
    """
    if isinstance(task, dict) and "skills" in task and task["skills"] is None:
        return None
    v = (task or {}).get("skills")
    return v if isinstance(v, list) else []


def _ado_status(manifest):
    """The ADO card's honesty-banner facts — MANIFEST EVIDENCE only, no network.

    The policy tab's rule applied to a second feature: the panel reports what
    the file proves (links /audit:sync wrote), never what the connector claims.
    `enabled`/`echo` are EFFECTIVE values (absent = on; a disabled connector
    reads echo off too) because the banner answers "what happens now", not
    "what is typed". Links count only int ids — the same shape the validator
    enforces — so junk never inflates the count."""
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado")
    configured = isinstance(ado, dict)
    ado = ado if configured else {}
    enabled = configured and ado.get("enabled") is not False
    linked = {"tasks": 0, "bugs": 0, "phases": 0}
    last = [None]

    def note(item, kind):
        link = item.get("ado") if isinstance(item, dict) else None
        if isinstance(link, dict) and isinstance(link.get("id"), int) \
                and not isinstance(link.get("id"), bool):
            linked[kind] += 1
            ts = link.get("lastSyncedAt")
            if isinstance(ts, str) and (last[0] is None or ts > last[0]):
                last[0] = ts

    # Phases are walked directly and tasks through `_mio.iter_tasks`: a phase can
    # carry an `ado` link with no tasks under it at all, and `iter_tasks` yields
    # nothing for such a phase. Two passes rather than one nested walk is free
    # here because every answer below is a count or a max — both order-free.
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict):
            note(ph, "phases")
    for _ph, t in _mio.iter_tasks(manifest):
        note(t, "tasks")
    for b in (manifest.get("bugs") or []):
        note(b, "bugs")
    return {"configured": configured,
            "enabled": enabled,
            "echo": enabled and ado.get("echo") is not False,
            "linked": linked, "lastSyncedAt": last[0]}


def _composition_view(manifest):
    meta = manifest.get("meta") or {}
    phases_out, tasks_out = [], []
    # `phases_out` and `tasks_out` are separate flat lists, so splitting the old
    # nested walk in two changes neither one's order: the phase rows stay in
    # document order and `_mio.iter_tasks` yields the tasks in document order too.
    # The task rows need the owning phase's id, which arrives with the task.
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        review = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        phases_out.append({"id": ph.get("id"), "title": ph.get("title"),
                           "status": ph.get("status"), "reviewModel": review.get("model"),
                           "area": _areas_of(ph.get("area")), "reviewSkill": ph.get("reviewSkill")})
    for ph, t in _mio.iter_tasks(manifest):
        tasks_out.append({
            "id": t.get("id"), "title": t.get("title"),
            "phaseId": ph.get("id"), "status": t.get("status"),
            "model": t.get("model"),
            "skills": _skills_of(t),
            # ov (F-P-5): Overview shows what the REPORT's table shows, so
            # it needs the same four values. They ride the composition
            # payload rather than a second endpoint — this is one manifest
            # read either way, and the Composition tab ignores what it does
            # not edit. Timestamps stay whole; the client cuts them.
            "risk": t.get("risk"),
            "commit": t.get("commit"),
            "startedAt": t.get("startedAt"),
            "completedAt": t.get("completedAt"),
        })
    # Every skill name the AREAS declare, deduped in registry order — the other
    # half of what the manifest spells (task rows carry their own). Shipped so
    # the client's inventory hint (skillHints, the modelHints analog) can see
    # a name that lives only in meta.areas without a second endpoint.
    area_skills = []
    for entry in _areas.registry(manifest).values():
        sk = entry.get("skills")
        for s in (sk if isinstance(sk, list) else []):
            if isinstance(s, str) and s.strip() and s.strip() not in area_skills:
                area_skills.append(s.strip())
    return {
        "meta": {"reviewSkill": meta.get("reviewSkill"),
                 "buildCommands": meta.get("buildCommands"),
                 "ado": meta.get("ado")},
        "areaSkills": area_skills,
        "adoStatus": _ado_status(manifest),
        "phases": phases_out, "tasks": tasks_out,
    }


def areas_state(project):
    """`GET /api/areas` — the registry, and every tag the phases actually use.

    Both halves, because the two disagree in both directions and each disagreement
    is worth seeing: a tag no entry covers resolves to no reviewer and no skills
    (usually a typo), and a registered area no phase uses is either a plan that has
    not been written yet or a rename that only got done on one side.

    Every verdict here comes from `_areas` — the same module the validator, the
    doctor and the status renderer resolve through — so this endpoint cannot
    develop its own opinion about what is registered.
    """
    config = read_config(project)
    mpath = _manifest_path(project, config)
    out = {"path": os.path.relpath(mpath, project) if _within(project, mpath)
           else None,
           "areas": {}, "tags": [], "findings": [], "warnings": []}
    if not _within(project, mpath):
        out["findings"] = ["refused: manifest path escapes project"]
        return out
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        out["findings"] = ["cannot read manifest: %s" % exc]
        return out
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    stored = meta.get("areas")
    out["areas"] = stored if isinstance(stored, dict) else {}
    f, w = _areas.validate_registry(stored)
    out["findings"], out["warnings"] = f, w
    reg = _areas.registry(manifest)
    used = {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for tag in _areas.areas_of(ph.get("area")):
            used.setdefault(tag, []).append(ph.get("id"))
    for tag in sorted(set(reg) | set(used)):
        entry = reg.get(tag) or {}
        root = _areas.root_of(entry)
        out["tags"].append({
            "tag": tag,
            "registered": tag in reg,
            "phases": used.get(tag, []),
            "root": root or None,
            # Resolved here rather than in the browser: the panel already learned
            # once (c6) that a value it SHOWS and a value the server computes have
            # to come from one function or the two eventually disagree.
            "rootExists": bool(root) and os.path.isdir(os.path.join(project, root)),
            "description": entry.get("description"),
            "reviewSkill": entry.get("reviewSkill"),
            "skills": entry.get("skills") if isinstance(entry.get("skills"), list)
            else [],
        })
    return out

_JOURNAL = {"tried": False, "mod": None}


def _journalmod():
    """`audit-journal.py`, loaded by path — or None, which is the normal answer
    today: the module ships with v0.29 and this call site ships before it, on
    purpose, so that the release which adds the journal does not also have to reach
    back into every writer. Loaded once; a missing file is not retried per save."""
    if not _JOURNAL["tried"]:
        _JOURNAL["tried"] = True
        path = os.path.join(_HERE, "audit-journal.py")
        if os.path.isfile(path):
            try:
                _JOURNAL["mod"] = _loader.load(path, modname="audit_journal")
            except Exception:
                _JOURNAL["mod"] = None
    return _JOURNAL["mod"]

JOURNAL_PAGE = 200


def journal_state(project, limit=JOURNAL_PAGE):
    """`GET /api/journal` — the recent rows, and whether the chain still holds.

    Both halves in one response, because either alone misleads. A list of rows with
    no verdict invites the reader to trust it; a verdict with no rows is a claim
    about something they cannot see. The verdict comes from `audit-journal.verify`
    — the same function the doctor and the CLI call — so the panel cannot develop
    its own opinion about what counts as intact.

    Read-only, and it stays that way: the journal is written by the writers it
    records, never by a request for it.
    """
    out = {"enabled": True, "dir": None, "rows": [], "verify": None,
           "available": False}
    mod = _journalmod()
    if mod is None:
        # This install has no journal module at all (pre-0.29). Reported rather
        # than 404'd: "there is no journal here" is an answer.
        return out
    config = read_config(project)
    out["enabled"] = bool(mod.enabled(config))
    try:
        res = mod.verify(project, config)
        out["available"] = True
        out["verify"] = {k: res[k] for k in
                         ("ok", "exists", "rows", "findings", "warnings")}
        out["dir"] = (os.path.relpath(res["dir"], project)
                      if _within(project, res["dir"]) else None)
        rows = mod.read_all(project, config)
        out["rows"] = list(reversed(rows[-limit:]))     # newest first
        out["truncated"] = len(rows) > limit
    except Exception as exc:
        out["verify"] = {"ok": False, "exists": False, "rows": 0,
                         "findings": ["could not read the journal: %s" % exc],
                         "warnings": []}
    return out


def help_state():
    """`GET /api/help` — what every field means, and how the four concepts work.

    Costs nothing to ask and nothing to answer: the field text is EXTRACTED from
    the two shipped schemas at request time, so the drawer cannot drift from the
    document a reader is told to trust, and the concept pages derive every
    executable rule from the code that executes it (`_help` states which). The
    conversational half — the `audit:guide` agent — is a card in this payload
    rather than something the panel spawns: a question a static page already
    answers should not silently bill for a model.

    Project-independent, and deliberately so. It takes no `project` argument
    because there is nothing here to scope: the live verdicts are `/api/policy`,
    the live trail is `/api/journal`, and mixing documentation with state would let
    a reader take a worked example for their own repository.
    """
    return _help.payload()


def help_field(path, doc):
    """`GET /api/help?path=usage.pricing.opus.in&doc=config` — one field.

    The drawer holds a path into a DOCUMENT and the help table is keyed by SHAPES,
    and exactly one thing in this product knows how to get from one to the other:
    `_help.entry_for`. Asking it over HTTP costs a localhost round trip and buys
    the guarantee the policy tab already has — the browser is handed an answer, not
    the machinery to compute one, so a second implementation cannot drift into
    disagreeing with the first.

    `found:false` rather than a 404: "nothing documents this path" is an answer the
    drawer can render, and a 404 would be indistinguishable from a panel talking to
    an install with no help endpoint at all.
    """
    res = _help.entry_for(path, doc)
    if res is None:
        return {"found": False, "path": path, "doc": doc}
    out = dict(res)
    out["found"] = True
    return out

def _policy_rules(policy, kind, names):
    """Every pattern the block states for `kind`, with what it matches TODAY.

    The switchboard's per-capability switches can only ever write EXACT names, and
    a policy is not obliged to be written that way: `code-*` is one rule deciding
    ten rows, and a rule aimed at something nobody has installed decides none. Both
    are invisible in a table of capabilities, and a form that cannot show a rule
    cannot be trusted to save one — the PUT replaces the block wholesale, so a rule
    this UI does not represent is a rule it would quietly destroy.

    Matched by `_policy.matches`, the function the guard itself matches with, so
    "this pattern covers these three" is the same claim the verdict column makes.

    Deny before allow, and project before area, because that is the order `resolve`
    reads them in — a list in resolution order can be read top-down as the reason.

    v0.38: each row carries `dead` — `_policy.dead_patterns`' verdict that the
    pattern matches neither a discovered name of this kind nor one of audit's own
    (`n: 0` alone cannot say that: `audit:*` covers no DISCOVERED name on a bare
    machine yet names components the plugin ships). Computed here so the client
    renders the flag and never matches a pattern itself — the same bargain the
    verdict column strikes — and so the doctor, which calls the same function
    over the same walk, cannot disagree with this page about which rule is inert.
    """
    out = []
    kcfg = policy.get(kind) if isinstance(policy.get(kind), dict) else {}
    dead = set()
    try:
        dead = set(_policy.dead_patterns(policy, kind, names))
    except Exception:
        dead = set()

    def add(scope, listname, patterns):
        # A LIST, not merely something iterable. `"deny": "nope"` is a shape the
        # validator calls a finding and a hand-edited file can still hold, and
        # iterating it yields four one-letter rules — a form inventing four rules
        # the file does not contain, each with its own remove button.
        if not isinstance(patterns, list):
            return
        for pat in patterns:
            if not isinstance(pat, str) or not pat.strip():
                continue
            hits = [n for n in names if _policy.matches(n, [pat])]
            out.append({"scope": scope, "list": listname, "pattern": pat,
                        "matches": hits[:6], "n": len(hits),
                        "dead": (scope, listname, pat.strip()) in dead})

    add(None, "deny", kcfg.get("deny"))
    add(None, "allow", kcfg.get("allow"))
    areas = kcfg.get("areas") if isinstance(kcfg.get("areas"), dict) else {}
    for tag in sorted(areas):
        rule = areas.get(tag)
        if isinstance(rule, dict):
            add(tag, "deny", rule.get("deny"))
            add(tag, "allow", rule.get("allow"))
    return out


def _policy_enforcement(project, config):
    """Has the guard hook ever actually run here?

    The one question a switchboard full of `deny` verdicts must not leave
    unanswered. Subagents do not inherit parent hooks on every Claude Code version
    (anthropics/claude-code#43772), and where that is true the policy is advisory —
    a page that draws a denial next to a capability while nothing is dispatching
    the matchers would be claiming enforcement nobody has.

    The evidence is the marker `guard-capabilities.py` writes when it runs with a
    live policy, read here exactly as `/audit:doctor` reads it: the hook's own
    `SEEN_FILE` constant and the config's own `state_dir`, never a path spelled out
    a second time in this file. The age is reported and the judgement is not — how
    stale is too stale is the doctor's call, and a threshold restated here is a
    threshold that can disagree with it.
    """
    out = {"seen": False, "ageDays": None}
    try:
        cfg_mod = _cores()[3]
        gc_mod = _load("audit_guard_capabilities",
                       os.path.join(_HERE, "..", "hooks", "guard-capabilities.py"))
        import pathlib
        marker = os.path.join(
            str(cfg_mod.state_dir(pathlib.Path(project), config)), gc_mod.SEEN_FILE)
        age = (time.time() - os.path.getmtime(marker)) / 86400.0
        out["seen"] = True
        out["ageDays"] = round(age, 2)
    except Exception:
        pass
    return out


def _policy_areas_view(reg, active, tags):
    """The area columns: every tag a rule could be aimed at, and whether it is LIVE.

    An area rule only applies while some phase in that area has work in progress
    (`_config.active_area_tags`, and `_active_area_tags` here) — so a column of
    denials for a dormant area decides nothing today and will decide everything the
    moment that phase starts. That is the fact this view exists to carry: the tag,
    whether it is active, and where the tag came from, since a rule may legitimately
    be written for a free-text tag the registry never registered.
    """
    out = []
    for tag in tags:
        entry = reg.get(tag) if isinstance(reg, dict) else None
        out.append({"tag": tag, "active": tag in (active or []),
                    "registered": isinstance(entry, dict),
                    "description": (entry or {}).get("description")
                    if isinstance(entry, dict) else None})
    return out


def policy_state(project):
    """`GET /api/policy` — the block, and what it RESOLVES TO for what is installed.

    The block alone is unreadable as governance: `{"default": "deny", "allow":
    ["code-*"]}` is four words that decide the fate of every skill on the machine,
    and nobody can hold the cross-product in their head. So the verdict for each
    discovered capability is computed here, by `_policy.resolve` — the same function
    the guard hook calls — and shipped alongside. A preview that ran its own
    matching would eventually disagree with the guard, and disagreeing about a
    denial is the one place a panel must not be creative.

    Every verdict carries its `basis` for the same reason the hook's refusal does.

    MCP is the one kind whose rows are STAND-INS: what is discoverable is a server
    name, while a policy matches whole tool names, so the row for server `github` is
    evaluated as `mcp__github__*` and says so via `standIn`. A rule aimed at one
    tool of that server therefore does not move the server's row — which is true,
    and better said than quietly averaged.
    """
    config = read_config(project)
    policy = _policy.policy_cfg(config)
    findings, warnings = _policy.validate_policy(config.get("policy"))
    mpath = _manifest_path(project, config)
    try:
        manifest = _mio.load_manifest_safe(mpath)
    except Exception:
        manifest = {}
    active = _active_area_tags(manifest)
    reg = _areas.registry(manifest)
    found = discover(project)
    out = {
        "policy": policy,
        "stored": config.get("policy") if isinstance(config.get("policy"), dict)
        else None,
        "active": _policy.is_active(policy),
        "onViolation": policy.get("onViolation"),
        "activeAreas": active,
        # Registered, used, or live — the same union `areas_state` reports, because
        # a rule can legitimately be written for a tag the registry does not carry
        # (free-text tagging is still legal) and a switchboard that offered only
        # registered areas would silently hide the rules aimed at the others.
        "areas": sorted(set(reg) | set(_areas.used_tags(manifest)) | set(active)),
        "required": _policy.required_names(),
        "kinds": list(_policy.KINDS),
        "onViolationChoices": list(_policy.ON_VIOLATION),
        "findings": findings, "warnings": warnings,
        # Whether anything is enforcing this at all. Served with the verdicts and
        # not on a separate endpoint, because it is a qualifier ON the verdicts.
        "enforcement": _policy_enforcement(project, config),
        "resolved": {}, "rules": {},
    }
    out["areaInfo"] = _policy_areas_view(reg, active, out["areas"])
    for kind in _policy.KINDS:
        rows = []
        if kind == "mcp":
            names = [("mcp__%s__*" % s, s, True) for s in (found.get("mcp") or [])]
        else:
            names = [(e.get("name"), e.get("source"), False)
                     for e in (found.get(kind) or []) if e.get("name")]
        for name, source, stand_in in names:
            v = _policy.resolve(policy, kind, name, active_tags=active)
            rows.append({"name": name, "source": source, "standIn": stand_in,
                         "verdict": v["verdict"], "basis": v["basis"],
                         "rule": v["rule"], "area": v["area"],
                         "required": bool(_policy.matches(
                             name, _policy.required_patterns(kind)))})
        out["resolved"][kind] = rows
        out["rules"][kind] = _policy_rules(policy, kind,
                                           [r["name"] for r in rows])
    return out


def _active_area_tags(manifest):
    """The area tags of phases with work in progress — what scopes an area rule.

    The same question `_config.active_area_tags` answers for the hook, asked of a
    manifest already in hand rather than re-read from disk. Both walk the ASSEMBLED
    document and both use `_areas.areas_of`, so the panel's preview and the guard's
    decision cannot disagree about which areas are live.

    Kept off `_mio.iter_tasks` on purpose. "Running" is a property of the PHASE and
    a phase is running when its OWN status says so, tasks or not — `iter_tasks`
    yields nothing for a task-less phase, so an in_progress phase that has not been
    broken into tasks yet would stop scoping its area rules, which is the one
    direction a capability policy must not fail in.
    """
    tags = []
    for phase in (manifest or {}).get("phases") or []:
        if not isinstance(phase, dict):
            continue
        running = phase.get("status") == "in_progress" or any(
            isinstance(t, dict) and t.get("status") == "in_progress"
            for t in (phase.get("tasks") or []))
        if not running:
            continue
        for tag in _areas.areas_of(phase.get("area")):
            if tag not in tags:
                tags.append(tag)
    return tags

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
    """audit-lock.py, loaded by path. None if it cannot be loaded — the panel
    then shows the lock without a liveness verdict rather than showing nothing."""
    try:
        return _loader.load_script("audit-lock.py", modname="audit_lock")
    except Exception:
        return None


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
            led = str(_cores()[3].ledger_dir(project, config))
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
        cfg_mod = _cores()[3]
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

_MAX_FACTS = 20000


def usage_state(project):
    """Payload for the Usage tab.

    Ships FACTS rather than finished tables — compact positional arrays the browser
    re-aggregates on every filter change, so switching model/author/phase/range is
    instant and never round-trips. Beyond _MAX_FACTS hourly rows the facts are rolled
    up to daily first, which keeps the payload bounded on a long-lived ledger; the
    response says so via `rolled` rather than silently truncating.

    Read-only: no lock, no writes, nothing that can collide with a running phase."""
    _, _, _, cfg_mod = _cores()
    config = read_config(project)
    ucfg = cfg_mod.usage_cfg(config)
    ledger_dir = str(cfg_mod.ledger_dir(project, config))
    empty = {"enabled": bool(ucfg.get("enabled", True)), "ledgerDir": ledger_dir,
             "showCost": bool(ucfg.get("showCost", True)),
             "pricingAsOf": ucfg.get("pricingAsOf"),
             "pricingAsOfDeclared": _declared_as_of(config),
             "facts": [], "fields": [],
             # Every key the populated branch returns must appear here too: the
             # client reads this shape on a repo with no ledger yet, and a missing
             # key there is an `undefined` that only shows up on a fresh install.
             "phaseTitles": {}, "taskMeta": {}, "phaseBudgets": {},
             "routingAdvice": [], "monthlyPlan": {}, "phaseAreas": {},
             "areaOwners": {},
             "bands": ucfg.get("bands") or {},
             "counts": {"phases": 0, "tasks": 0, "models": 0, "authors": 0,
                        "sessions": 0, "days": 0, "from": None, "to": None},
             "rolled": False, "totalRows": 0}
    try:
        ul = _load("audit_usage_ledger", os.path.join(_HERE, "usage_ledger.py"))
        rows = ul.read_ledger(ledger_dir)
    except Exception:
        return empty
    if not rows:
        return empty

    # Orientation counts for the context line. Computed over the WHOLE ledger on
    # purpose — they describe the shape of the data you are looking at, not the
    # current filter — and `sessionId` deliberately never enters `facts`, where it
    # would multiply row cardinality for a number shown once.
    days = sorted({(r.get("ts") or "")[:10] for r in rows} - {""})
    counts = {
        "phases": len({r.get("phaseId") for r in rows if r.get("phaseId")}),
        "tasks": len({r.get("taskId") for r in rows if r.get("taskId")}),
        "models": len({r.get("model") for r in rows if r.get("model")}),
        "authors": len({r.get("author") for r in rows if r.get("author")}),
        "sessions": len({r.get("sessionId") for r in rows if r.get("sessionId")}),
        "days": len(days),
        "from": days[0] if days else None,
        "to": days[-1] if days else None,
    }

    rolled = len(rows) > _MAX_FACTS
    facts, seen = {}, 0
    for r in rows:
        seen += 1
        ts = r.get("ts") or ""
        key = (ts[:10] if rolled else ts, r.get("phaseId") or "--",
               r.get("taskId") or "--", r.get("model") or "unknown",
               r.get("author") or "unknown", r.get("agentType") or "orchestrator",
               r.get("attr") or "unattributed")
        slot = facts.get(key)
        if slot is None:
            slot = facts[key] = [0, 0.0, 0]
        slot[0] += sum(int(r.get(k) or 0) for k in ul.TOKEN_KEYS)
        slot[1] += float(r.get("costUSD") or 0.0)
        slot[2] += int(r.get("msgs") or 0)

    # Ship the small slice of manifest the analytics need — task status, risk and
    # attempts — so EVERY panel recomputes client-side under the current filter. The
    # alternative (server-computed metrics) would leave half the tab silently
    # ignoring the filter bar, which is worse than a slightly larger payload.
    titles, task_meta, budgets = {}, {}, {}
    mpath = _manifest_path(project, config)
    # ONE read for the five consumers below. They each used to call
    # `load_manifest_safe(mpath)` for themselves, which on a sharded manifest is
    # 1 index + 1 file per phase EVERY TIME: measured at 100 file opens and 5 JSON
    # parse passes for a 19-phase plan, per GET /api/usage, to answer five
    # questions about one document. Hoisting is safe outside the try blocks
    # because `load_manifest_safe` is total — it returns {} on any error and never
    # raises — so the guards below still cover exactly what they were protecting
    # against: the CONSUMERS (routing, monthly_activity, phase_tags, registry).
    # Reading once is also the more correct answer: five reads could straddle a
    # concurrent manifest write and ship five mutually inconsistent views of it.
    manifest = _mio.load_manifest_safe(mpath)
    try:
        # `titles`/`budgets` are per-PHASE and must cover a phase with no tasks
        # (it still has a name and can still declare a budget), so that half stays
        # a phase walk; the task half is `_mio.iter_tasks`. Three id-keyed dicts,
        # so the split costs nothing: the same document order still decides the
        # same last-wins winner it did when the two walks were nested.
        for ph in (manifest.get("phases") or []):
            if not isinstance(ph, dict) or not ph.get("id"):
                continue
            titles[ph["id"]] = ph.get("title") or ""
            # Same rule the validator enforces: 0, negative, boolean and
            # non-numeric all mean "no budget", never a budget of zero.
            b = ph.get("budgetUSD")
            if isinstance(b, (int, float)) and not isinstance(b, bool) and b > 0:
                budgets[ph["id"]] = float(b)
        for _ph, t in _mio.iter_tasks(manifest):
            if t.get("id"):
                task_meta[t["id"]] = {
                    "status": t.get("status"), "risk": t.get("risk") or "unrated",
                    "attempts": t.get("attempts") or 1,
                    "title": t.get("title") or ""}
    except Exception:
        titles, task_meta, budgets = {}, {}, {}

    # Needs the assembled manifest and the per-tier counts, so it cannot be done
    # on the client. Fail-soft: no advice is the normal outcome anyway.
    try:
        advice = ul.routing(manifest, rows,
                            ucfg.get("pricing")).get("advice") or []
    except Exception:
        advice = []

    # The Monthly card's plan half. Its ledger half is recomputed client-side
    # under the current filters; this half needs the manifest, so it ships from
    # here and the card labels it project-wide. Rows are deliberately NOT passed:
    # the client owns the month axis (its months union this dict's keys), and
    # the plan half's months are the plan's own events.
    try:
        monthly_plan = ul.monthly_activity(manifest, []).get("plan") or {}
    except Exception:
        monthly_plan = {}

    # The Usage tab's area filter joins each row's phaseId to the plan's tags at
    # READ time — area is a property of the plan, not of the moment of spend, so
    # re-tagging a phase re-attributes its whole ledger history with no backfill.
    # The join map ships with the facts; the client does the join per row.
    try:
        phase_areas = _areas.phase_tags(manifest)
    except Exception:
        phase_areas = {}

    # The advisory owner per registered area (v0.34 D3): {tag: owner}, only
    # for tags that DECLARE a non-null owner - an explicit null ("nobody") and
    # an undeclared owner read the same to the UI, which only ever displays.
    # panel.js joins UF.author against the VALUES for the person header's
    # "owns:" line, and titles the area select's options with them.
    try:
        area_owners = {}
        for _tag, _entry in _areas.registry(manifest).items():
            _o = _entry.get("owner")
            if isinstance(_o, str) and _o.strip():
                area_owners[_tag] = _o.strip()
    except Exception:
        area_owners = {}

    return {
        "enabled": bool(ucfg.get("enabled", True)),
        "ledgerDir": ledger_dir,
        "showCost": bool(ucfg.get("showCost", True)),
        "pricingAsOf": ucfg.get("pricingAsOf"),
        "pricingAsOfDeclared": _declared_as_of(config),
        "fields": ["ts", "phase", "task", "model", "author", "agent", "attr",
                   "tokens", "cost", "msgs"],
        "facts": [list(k) + [v[0], round(v[1], 6), v[2]]
                  for k, v in sorted(facts.items())],
        "phaseTitles": titles,
        "taskMeta": task_meta,
        "phaseBudgets": budgets,
        # Server-computed, unlike every other metric here: the counterfactual
        # re-prices the per-tier token counts, and `facts` are already aggregated
        # to [tokens, cost, msgs]. Shipping the breakdown to do it client-side
        # would multiply the payload to serve one paragraph. So this is a
        # statement about the PROJECT, and the panel labels it as such.
        "routingAdvice": advice,
        "monthlyPlan": monthly_plan,
        "phaseAreas": phase_areas,
        "areaOwners": area_owners,
        "bands": ucfg.get("bands") or {},
        "counts": counts,
        "rolled": rolled,
        "totalRows": seen,
    }


def report_paths(project):
    """(manifest, out_dir, html_path) for this project's report, or None.

    The output location is DERIVED, never taken from the request: there is no path
    parameter to traverse with. Both ends are re-checked against the project root
    anyway, because a manifestPath in config could point outside it."""
    config = read_config(project)
    mpath = _manifest_path(project, config)
    if not (os.path.isfile(mpath) and _within(project, mpath)):
        return None
    out_dir = os.path.dirname(os.path.abspath(mpath))
    if not _within(project, out_dir):
        return None
    try:
        rr = _load("audit_render_report", os.path.join(_HERE, "render-report.py"))
        manifest = _mio.load_manifest_safe(mpath)
        # `_report_basename` takes META, not the manifest — it reads
        # `reportBasename` off the mapping it is handed. Passed the whole manifest
        # it found no such key and always answered "audit-report", so on every
        # project that sets meta.reportBasename (the shipped example does) the
        # panel rendered the report correctly and then looked for it under the
        # wrong name: "wrote 2 files" followed by a 404.
        base = rr._report_basename(manifest.get("meta"), None)
    except Exception:
        base = "audit-report"
    return mpath, out_dir, os.path.join(out_dir, base + ".html")


def render_report(project):
    """Write the standalone HTML report (and its Markdown twin) for this project.

    Calls render-report.py's own `main` rather than shelling out: same code path
    the CLI takes, no interpreter discovery, and it works the same on Windows."""
    paths = report_paths(project)
    if not paths:
        return {"ok": False,
                "findings": ["no manifest to report on (or its path escapes the "
                             "project) — run /audit:init first"]}
    mpath, out_dir, html_path = paths
    try:
        rr = _load("audit_render_report", os.path.join(_HERE, "render-report.py"))
    except Exception as exc:
        return {"ok": False, "findings": ["cannot load the renderer: %s" % exc]}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = rr.main([mpath, "--out-dir", out_dir, "--format", "both"])
    except Exception as exc:
        return {"ok": False, "findings": ["render failed: %s" % exc]}
    if code != 0:
        return {"ok": False,
                "findings": ["renderer exited %s — run /audit:report for detail"
                             % code]}
    written = [ln[len("wrote "):] for ln in buf.getvalue().splitlines()
               if ln.startswith("wrote ")]
    return {"ok": True, "files": written,
            # Served back through this origin: a browser will not follow a file://
            # link from an http:// page, so handing over a filesystem path would
            # produce a button that silently does nothing.
            "href": "/report", "exists": os.path.isfile(html_path)}


def build_state(project):
    vm, vc, as_, _ = _cores()
    config = read_config(project)
    cfg_findings, cfg_warnings = vc.validate_config(config)
    mpath = _manifest_path(project, config)
    manifest, exists = None, os.path.isfile(mpath)
    rollup, m_findings = None, []
    composition = {"meta": {"reviewSkill": None, "buildCommands": None,
                            "ado": None},
                   "areaSkills": [],
                   "adoStatus": {"configured": False, "enabled": False,
                                 "echo": False,
                                 "linked": {"tasks": 0, "bugs": 0,
                                            "phases": 0},
                                 "lastSyncedAt": None},
                   "phases": [], "tasks": []}
    bugs = []
    if exists:
        try:
            manifest = _mio.load_manifest(mpath)   # dual-format: single-file OR index+shards
        except Exception as exc:
            m_findings = ["cannot parse manifest: %s" % exc]
        if isinstance(manifest, dict):
            m_findings, m_warn = vm.validate(manifest)
            rollup = as_.rollup(manifest, m_findings, m_warn)
            composition = _composition_view(manifest)
            bugs = _bugs_view(manifest)
    return {
        "project": project,
        "manifestPath": os.path.relpath(mpath, project),
        "manifestExists": exists,
        "manifestLocked": _audit_lock_held(project, config),
        "viewer": _viewer(project, config),
        "config": config,
        "defaults": _defaults(),
        "configFindings": cfg_findings,
        "configWarnings": cfg_warnings,
        "manifestFindings": m_findings,
        "composition": composition,
        "bugs": bugs,
        "rollup": rollup,
        "runStatus": _run_status(project, config, manifest),
    }


# --- selftest -------------------------------------------------------------------
def _selftest():
    """The read-side cases, moved here with P12.3 and carrying their original
    labels. What stayed in panel-server.py is what asserts UI_HTML, an HTTP round
    trip, or panel-server's own source: those are claims about the server, not
    about the payloads this module builds."""
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    import pathlib
    import shutil
    import tempfile

    _src = _src_of_this_file()

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer. panel-server keeps the real
        `_atomic_write_json`; nothing in THIS module writes JSON, so rather than
        move a writer a read module has no use for, the fixtures go straight
        through `_manifest_io` — the same implementation that one delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-state-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(_config_path(proj), {"trivialLineThreshold": 40})
    mpath = _manifest_path(proj, read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    # --- what the config declares, and what merely defaults ---------------------
    check("_declared_as_of separates a project's own value from the default",
          _declared_as_of({"usage": {"pricingAsOf": "2026-01-02"}}) is True
          and _declared_as_of({"usage": {"showCost": True}}) is False
          and _declared_as_of({}) is False
          and _declared_as_of({"usage": {"pricingAsOf": "   "}}) is False
          and _declared_as_of({"usage": {"pricingAsOf": 20260102}}) is False)

    check("_areas_of normalizes string/list/absent",
          _areas_of("x") == ["x"] and _areas_of(["a", "b"]) == ["a", "b"]
          and _areas_of(None) == [])

    # --- v0.37 B1: the three skill states, as the panel payload carries them ----
    # Explicit null is an ANSWER ("none applies" — it stops the area fallback)
    # and the view must ship it AS null; flattening it to [] made the opt-out
    # indistinguishable from "unconsidered" on every panel surface.
    check("_skills_of keeps the three states apart: null stays None, absent "
          "and junk read as []",
          _skills_of({"skills": None}) is None
          and _skills_of({}) == []
          and _skills_of({"skills": "x"}) == []
          and _skills_of({"skills": ["a"]}) == ["a"])
    _cv3 = _composition_view({
        "meta": {"areas": {"api": {"root": "src", "skills": ["conv", "sec"]},
                           "web": {"root": "w", "skills": ["conv"]}}},
        "phases": [{"id": "PX", "title": "p", "status": "pending",
                    "tasks": [{"id": "PX.1", "title": "t", "status": "pending",
                               "skills": None}]}]})
    check("the composition view ships the opt-out as null, not as []",
          _cv3["tasks"][0]["skills"] is None)
    check("...and carries the area-declared skill names, deduped, so the "
          "client's inventory hint sees every name the manifest spells",
          _cv3.get("areaSkills") == ["conv", "sec"])

    # --- connector v2: the ADO card's read side ---------------------------------
    # adoStatus is MANIFEST EVIDENCE only (links /audit:sync wrote) — the panel
    # reports what the file proves, never what the connector claims; the policy
    # tab's rule, applied to a second feature. No network in the panel, ever.
    check("the composition view ships meta.ado verbatim - the card's form source",
          _composition_view({"meta": {"ado": {"organization": "o"}},
                             "phases": []})["meta"]["ado"]
          == {"organization": "o"})
    _as1 = _ado_status({"meta": {}, "phases": []})
    check("adoStatus: an unconfigured manifest reads configured=false, "
          "nothing linked, no effective switches",
          _as1 == {"configured": False, "enabled": False, "echo": False,
                   "linked": {"tasks": 0, "bugs": 0, "phases": 0},
                   "lastSyncedAt": None})
    _as2 = _ado_status({"meta": {"ado": {"organization": "o",
                                         "enabled": False}}, "phases": []})
    check("adoStatus: enabled:false reads off (echo effectively off too) "
          "while staying configured",
          _as2["configured"] is True and _as2["enabled"] is False
          and _as2["echo"] is False)
    _as3 = _ado_status({"meta": {"ado": {"organization": "o"}}, "phases": []})
    check("adoStatus: absent switches read as their defaults - enabled on, "
          "echo on",
          _as3["configured"] is True and _as3["enabled"] is True
          and _as3["echo"] is True
          and _as3["linked"] == {"tasks": 0, "bugs": 0, "phases": 0})
    _as4 = _ado_status({
        "meta": {"ado": {"organization": "o", "echo": False}},
        "phases": [{"id": "P1", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-02T00:00:00Z"},
                    "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                               "ado": {"id": 7,
                                       "lastSyncedAt": "2026-08-03T00:00:00Z"}},
                              {"id": "P1.2", "title": "t", "status": "pending",
                               "ado": "junk"}]}],
        "bugs": [{"id": "BUG-1", "title": "b", "status": "open",
                  "ado": {"id": 8, "lastSyncedAt": "2026-08-01T00:00:00Z"}},
                 {"id": "BUG-2", "title": "b", "status": "open",
                  "ado": {"id": "x"}}]})
    check("adoStatus: linked counts by kind with junk shapes skipped "
          "(int ids only), the newest lastSyncedAt wins, echo:false honoured",
          _as4["linked"] == {"tasks": 1, "bugs": 1, "phases": 1}
          and _as4["lastSyncedAt"] == "2026-08-03T00:00:00Z"
          and _as4["echo"] is False and _as4["enabled"] is True)
    check("the composition view carries adoStatus (and a manifest with no "
          "meta.ado still gets the full shape)",
          _composition_view({"meta": {}, "phases": []})
          .get("adoStatus", {}).get("configured") is False)
    # _as5 pins why the phase half of this walk is NOT `_mio.iter_tasks`: a phase
    # /audit:sync has pushed but nobody has broken into tasks yet still carries a
    # link and a timestamp, and `iter_tasks` yields nothing at all for it. The
    # fixture puts the NEWEST timestamp on that phase so a version that dropped it
    # gets both the count AND lastSyncedAt wrong — a same-or-older stamp there
    # would let the two versions agree on the second half by accident.
    _as5 = _ado_status({
        "meta": {"ado": {"organization": "o"}},
        "phases": [{"id": "P1", "title": "linked, no tasks yet",
                    "status": "pending",
                    "ado": {"id": 4, "lastSyncedAt": "2026-08-09T00:00:00Z"}},
                   {"id": "P2", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-01T00:00:00Z"},
                    "tasks": [
                       {"id": "P2.1", "title": "t", "status": "pending",
                        "ado": {"id": 5,
                                "lastSyncedAt": "2026-08-04T00:00:00Z"}}]}]})
    check("adoStatus: a phase with a link and NO tasks is still counted, and "
          "still wins lastSyncedAt",
          _as5["linked"] == {"tasks": 1, "bugs": 0, "phases": 2}
          and _as5["lastSyncedAt"] == "2026-08-09T00:00:00Z")

    # _bugs_view: the bug rows behind the strip. Every derived field is decided in
    # Python by the SAME functions the rollup counts with.
    bm = {"phases": [{"id": "P1", "title": "One", "status": "in_progress", "tasks": [
              {"id": "P1.1", "title": "fix it", "status": "done", "bugId": "BUG-1"},
              {"id": "P1.2", "title": "later", "status": "pending", "bugId": "BUG-2"}]}],
          "bugs": [
              {"id": "BUG-1", "title": "a", "status": "open", "severity": "high",
               "taskId": "P1.1"},
              {"id": "BUG-2", "title": "b", "status": "open", "severity": "critical",
               "taskId": "P1.2"},
              {"id": "BUG-3", "title": "c", "status": "wontfix", "severity": "high"}]}
    bv = _bugs_view(bm)
    by_id = {b["id"]: b for b in bv}
    check("_bugs_view resolves a bug through its task: fixed when the task is done, "
          "with the stored value kept so it does not read as hand-edited",
          by_id["BUG-1"]["status"] == "fixed" and by_id["BUG-1"]["reported"] == "open"
          and by_id["BUG-2"]["status"] == "open")
    check("_bugs_view names the phase behind the linked task",
          by_id["BUG-1"]["phaseId"] == "P1")
    # A regex in the browser would be a third opinion on 'is this high?' — and the
    # first spelling it would miss is `critical`, which is the one that matters.
    _rup = _cores()[2].rollup(bm, [], [])
    check("_bugs_view's open/high agree with the rollup's counts, by construction",
          sum(1 for b in bv if b["open"]) == _rup["bugs"]["open"]
          and sum(1 for b in bv if b["open"] and b["high"])
          == _rup["bugs"]["openHighSeverity"] == 1
          and by_id["BUG-2"]["high"] is True)
    check("_bugs_view on a manifest with no bugs is an empty list, not an error",
          _bugs_view({"phases": []}) == [])

    # --- v0.28: the areas registry, as GET reports it ---------------------------
    # A sharded fixture on purpose: `meta` lives on the INDEX there, and this
    # endpoint has to read the ASSEMBLED document to see the phases at all.
    _aproj = tempfile.mkdtemp(prefix="state-areas-")
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
        _st = areas_state(_aproj)
        # `.get` and not `[...]`: a missing tag is exactly what a broken version of
        # this endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _bytag = {t["tag"]: t for t in _st["tags"]}
        _tag = lambda name: _bytag.get(name) or {}          # noqa: E731
        check("areas GET returns the registry as stored",
              set(_st["areas"]) == {"api", "unused"})
        check("areas GET lists a registered tag with the phases using it",
              _tag("api").get("registered") and _tag("api").get("phases") == ["P1"])
        check("areas GET says a root that exists exists",
              _tag("api").get("rootExists") is True)
        check("areas GET lists a tag no entry covers - the typo case, which "
              "resolves to no reviewer and no skills",
              _tag("apu").get("registered") is False
              and _tag("apu").get("phases") == ["P2"])
        check("areas GET also lists a registered area no phase uses - a rename "
              "done on one side only looks exactly like this",
              _tag("unused").get("registered")
              and _tag("unused").get("phases") == [])
        check("areas GET carries the resolved reviewer of a registered area",
              _tag("api").get("reviewSkill") == "backend-review")
        check("areas GET refuses a manifest path that escapes the project rather "
              "than reading it",
              areas_state(os.path.join(_aproj, "nope"))["areas"] == {})
    finally:
        shutil.rmtree(_aproj, ignore_errors=True)


    # --- v0.30: the policy block's rules, and whether anything enforces them ----
    # The verdict cases that need a fixture full of discovered capabilities stay
    # with the HTTP round trip in panel-server; what moved is the part that is a
    # function of the block itself, plus the enforcement marker.
    check("deny is listed before allow within a scope, because that is the "
          "order the verdict is decided in",
          [(r["list"], r["pattern"]) for r in _policy_rules(
              {"skills": {"allow": ["a"], "deny": ["d"]}}, "skills", [])]
          == [("deny", "d"), ("allow", "a")])
    _many = _policy_rules({"skills": {"deny": ["a*"]}}, "skills",
                          ["a%d" % i for i in range(9)])
    check("a pattern covering more names than fit is capped for display while "
          "the count stays true - a truncated list read as the total would "
          "understate what one rule decides",
          _many[0]["n"] == 9 and len(_many[0]["matches"]) == 6)
    check("a blank or non-string pattern is skipped rather than rendered as an "
          "empty rule nobody can remove",
          _policy_rules({"skills": {"deny": ["  ", "", 7, "real"]}},
                        "skills", []) == [
              {"scope": None, "list": "deny", "pattern": "real",
               "matches": [], "n": 0, "dead": True}])
    # v0.38: the dead flag - the server's own "names nothing" verdict, computed
    # by _policy.dead_patterns beside the guard's matcher, so the client renders
    # it and never matches a pattern itself.
    check("a pattern matching nothing discovered and nothing of audit's own is "
          "marked dead; a name the inventory satisfies is not",
          [(r["pattern"], r["dead"]) for r in _policy_rules(
              {"skills": {"deny": ["ghost-*", "real-skill"]}}, "skills",
              ["real-skill"])]
          == [("ghost-*", True), ("real-skill", False)])
    check("a pattern that names only audit's own components is not dead - the "
          "plugin ships them, so they are always installed",
          _policy_rules({"skills": {"deny": ["x"], "allow": ["audit:*"]}},
                        "skills", [])[1]["dead"] is False)
    check("mcp rules are judged both ways against the server stand-ins - a rule "
          "for one tool of an installed server is alive, one for an absent "
          "server is dead",
          [r["dead"] for r in _policy_rules(
              {"mcp": {"deny": ["mcp__srv__one_tool", "mcp__gone__*"]}},
              "mcp", ["mcp__srv__*"])] == [False, True])
    # Called through a wrapper so the failure is a named FAIL and not a
    # traceback: this endpoint feeds a form, a form's job is to survive a file
    # somebody hand-edited, and an assertion that dies while proving that
    # reports the wrong thing twice over — nothing about the defect, and a
    # crash that looks like one.
    def _rules_safe(pol, kind, names):
        try:
            return _policy_rules(pol, kind, names)
        except Exception as exc:                 # noqa: BLE001 - that is the check
            return "raised %s" % type(exc).__name__
    check("a malformed kind block yields no rules instead of raising",
          _rules_safe({"skills": "nonsense"}, "skills", ["x"]) == []
          and _rules_safe({}, "skills", ["x"]) == []
          and _rules_safe({"skills": {"deny": "nope"}}, "skills", ["x"]) == [])

    # What scopes an area rule, and why this walk is NOT `_mio.iter_tasks`. The
    # first phase is in_progress with NO tasks at all — the state a phase is in
    # between /audit:phase starting it and its first task being minted — and
    # `iter_tasks` yields nothing for it. The second phase is the same shape the
    # other way round (dormant phase, running task), so the case separates the
    # two rules instead of proving only one of them.
    check("an in_progress phase with no tasks still scopes its area, and a "
          "dormant phase holding a running task does too",
          _active_area_tags({"phases": [
              {"id": "P1", "status": "in_progress", "area": "infra"},
              {"id": "P2", "status": "pending", "area": ["web"], "tasks": [
                  {"id": "P2.1", "status": "in_progress"}]},
              {"id": "P3", "status": "pending", "area": "quiet", "tasks": [
                  {"id": "P3.1", "status": "pending"}]},
          ]}) == ["infra", "web"])

    _pproj = tempfile.mkdtemp(prefix="state-policy-")
    try:
        os.makedirs(os.path.join(_pproj, ".claude"), exist_ok=True)
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _ps = policy_state(_pproj)
        # Whether anything is enforcing any of this. A page full of `deny` verdicts
        # that cannot say whether the hook has ever run would be claiming
        # enforcement nobody has - the doctor's warning, on the surface that shows
        # the denials.
        check("with no marker, enforcement is reported as never seen rather than "
              "assumed",
              _ps["enforcement"] == {"seen": False, "ageDays": None})
        _sd = str(_cores()[3].state_dir(pathlib.Path(_pproj), read_config(_pproj)))
        os.makedirs(_sd, exist_ok=True)
        _gc = _load("audit_guard_capabilities_t",
                    os.path.join(_HERE, "..", "hooks", "guard-capabilities.py"))
        with open(os.path.join(_sd, _gc.SEEN_FILE), "w", encoding="utf-8") as _fh:
            _fh.write("{}")
        _pe = _policy_enforcement(_pproj, read_config(_pproj))
        check("with the guard's own marker present it is reported as seen, with an "
              "age and no verdict about whether that age is too old - how stale is "
              "too stale is /audit:doctor's judgement, and a second threshold here "
              "is one that can disagree with it",
              _pe["seen"] is True and _pe["ageDays"] is not None
              and _pe["ageDays"] < 1 and set(_pe) == {"seen", "ageDays"})
        check("...and it is found at the path the hook writes: the config's own "
              "state_dir and the hook's own SEEN_FILE, neither spelled out twice",
              os.path.isfile(os.path.join(_sd, _gc.SEEN_FILE))
              and _gc.SEEN_FILE == "capability-guard.json")
        check("an unreadable project reports never-seen rather than raising",
              _policy_enforcement(os.path.join(_pproj, "nope"), {})["seen"] is False)
    finally:
        shutil.rmtree(_pproj, ignore_errors=True)


    # --- the audit locks, and whether the run behind one is alive ---------------
    ld = os.path.join(tmp, "audit-locks")
    os.makedirs(ld)
    _atomic_write_json(os.path.join(ld, "index.lock"), {"hostname": "hi", "startedAt": "t"})
    _atomic_write_json(os.path.join(ld, "phase-P1.lock"), {"hostname": "hp", "startedAt": "t2"})
    li = _lock_info(ld)
    check("_lock_info reads the index lock", (li["index"] or {}).get("hostname") == "hi")
    check("_lock_info reads a phase lock", (li["phases"].get("P1") or {}).get("hostname") == "hp")

    # C1 — the badge says "running", which is a claim about a live process.
    import platform as _pf
    import subprocess as _sp
    import time as _t
    _here = _pf.node()
    _old = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() - 95 * 60))
    _atomic_write_json(os.path.join(ld, "phase-P2.lock"),
                       {"hostname": _here, "pid": os.getpid(), "startedAt": _old})
    _d = _sp.Popen([sys.executable, "-c", "pass"]); _d.wait()
    _atomic_write_json(os.path.join(ld, "phase-P3.lock"),
                       {"hostname": _here, "pid": _d.pid,
                        "startedAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())})
    li = _lock_info(ld)
    check("lock verdict: a 95-min-old run with a live pid is live",
          li["phases"]["P2"].get("live") is True)
    check("lock verdict: a 1-min-old run whose pid is gone is not",
          li["phases"]["P3"].get("live") is False)
    check("lock verdict: each carries the basis behind it",
          bool(li["phases"]["P2"].get("liveBasis"))
          and bool(li["phases"]["P3"].get("liveBasis")))
    check("lock verdict: a pid-less lock gets one too (age fallback)",
          li["phases"]["P1"].get("live") is not None)
    os.remove(os.path.join(ld, "phase-P2.lock"))
    os.remove(os.path.join(ld, "phase-P3.lock"))

    u = usage_state(proj)
    check("usage_state on a project with no ledger is empty, not an error",
          u["facts"] == [] and u["totalRows"] == 0 and "ledgerDir" in u)
    led = os.path.join(proj, ".claude", "usage")
    os.makedirs(led, exist_ok=True)
    with open(os.path.join(led, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
        for i, (model, author) in enumerate(
                (("claude-opus-5", "a@x.io"), ("claude-haiku-4-5", "b@x.io"))):
            fh.write(json.dumps({
                "ts": "2026-08-0%dT1%d" % (i + 1, i), "sessionId": "s%d" % i,
                "phaseId": "P1", "taskId": "P1.%d" % (i + 1), "attr": "task",
                "model": model, "author": author, "agentType": "audit-executor",
                "msgs": 2, "in": 5, "out": 100, "cacheW5m": 0, "cacheW1h": 0,
                "cacheR": 50, "costUSD": 0.25}) + "\n")
        fh.write("{ torn line\n")
    u = usage_state(proj)
    check("usage_state reads the ledger into positional facts",
          len(u["facts"]) == 2 and u["fields"][0] == "ts"
          and len(u["facts"][0]) == len(u["fields"]))
    check("usage_state tolerates a torn ledger line", u["totalRows"] == 2)
    check("usage_state carries phase titles for labelling",
          isinstance(u["phaseTitles"], dict))
    check("usage_state does not roll up a small ledger", u["rolled"] is False)
    check("usage facts carry no prompt content — only dimensions and counts",
          all(len(f) == 10 for f in u["facts"]))

    # --- one manifest read per /api/usage ---------------------------------------
    # The payload answers five questions about ONE document (titles/taskMeta/
    # budgets, routingAdvice, monthlyPlan, phaseAreas, areaOwners) and each used to
    # re-read it — on a sharded plan that is 1 index + 1 file per phase, per
    # question. COUNTED rather than asserted-present: a source pin cannot tell one
    # call from five, which is exactly the regression this guards.
    _lms_calls = [0]
    _real_lms = _mio.load_manifest_safe

    def _counting_lms(path):
        _lms_calls[0] += 1
        return _real_lms(path)

    _mio.load_manifest_safe = _counting_lms
    try:
        _hoisted = usage_state(proj)
    finally:
        _mio.load_manifest_safe = _real_lms
    check("usage_state reads the manifest exactly ONCE for all five of its "
          "manifest-derived fields (each used to re-read it)",
          _lms_calls[0] == 1)
    check("counting the reads did not change the payload",
          _hoisted == u)
    # The other direction, and the one that looks vacuous: "read once" must mean
    # once PER REQUEST, not once per process. A manifest memoized across requests
    # would satisfy the count above and then serve a stale plan forever — the
    # `_VIEWER_CACHE` failure — so edit the plan on disk and require the next
    # response to carry it.
    _m_before = _mio.load_manifest_safe(mpath)
    try:
        _m_edited = json.loads(json.dumps(_m_before))
        _m_edited["phases"][0]["title"] = "Retitled between requests"
        _atomic_write_json(mpath, _m_edited)
        check("the single read is per REQUEST — a plan edited between two calls "
              "shows up in the second",
              usage_state(proj)["phaseTitles"].get("P1")
              == "Retitled between requests")
    finally:
        _atomic_write_json(mpath, _m_before)
    check("...and restoring the plan restores the payload",
          usage_state(proj)["phaseTitles"].get("P1") == "P")

    _saved = globals()["_MAX_FACTS"]
    try:
        globals()["_MAX_FACTS"] = 1
        ru = usage_state(proj)
        check("oversized ledger rolls hourly facts up to daily, and says so",
              ru["rolled"] is True and all(len(f[0]) == 10 for f in ru["facts"]))
    finally:
        globals()["_MAX_FACTS"] = _saved
    _cfg_path = os.path.join(proj, ".claude", "audit.config.json")
    _prev_cfg = (open(_cfg_path, encoding="utf-8").read()
                 if os.path.isfile(_cfg_path) else None)
    try:
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"enabled": False, "showCost": False}}, fh)
        du = usage_state(proj)
        check("usage_state reports metering off so the tab can explain itself",
              du["enabled"] is False and du["showCost"] is False)
        # The empty branch's own comment requires it: every key the populated
        # branch returns must appear here too, or a fresh install reads undefined.
        check("the no-ledger shape carries pricingAsOfDeclared as well, so a "
              "fresh install does not read undefined",
              "pricingAsOfDeclared" in du and du["pricingAsOfDeclared"] is False)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": "2026-01-02"}}, fh)
        check("a declared date is reported as declared, and travels with it",
              usage_state(proj)["pricingAsOfDeclared"] is True
              and usage_state(proj)["pricingAsOf"] == "2026-01-02")
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"showCost": True}}, fh)
        _dd = usage_state(proj)
        check("an undeclared one still carries the merged default as the VALUE, "
              "flagged as undeclared - the client decides, the server does not lie",
              _dd["pricingAsOfDeclared"] is False and _dd["pricingAsOf"])
    finally:
        if _prev_cfg is None:
            os.remove(_cfg_path)
        else:
            with open(_cfg_path, "w", encoding="utf-8") as fh:
                fh.write(_prev_cfg)

    # --- monthlyPlan (C2): the Monthly card's server-shipped plan half ----------
    # The ledger half of that card is recomputed in the browser under the current
    # filters; the plan half cannot be (the client has no manifest), so it ships
    # here. Key parity first: the empty branch must carry every key the populated
    # branch returns — the pinned rule beside the empty dict — so a fresh install
    # reads {} and never undefined.
    _mp_empty = usage_state(os.path.join(tmp, "no-such-proj"))
    check("usage_state ships monthlyPlan in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          _mp_empty["facts"] == [] and "monthlyPlan" in _mp_empty
          and _mp_empty["monthlyPlan"] == {})
    with open(mpath, encoding="utf-8") as _fh:
        _orig_manifest = json.load(_fh)
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2},
            "phases": [{"id": "P1", "title": "P", "status": "done",
                        "mergedAt": "2026-08-06T10:00:00Z",
                        "tasks": [{"id": "P1.1", "title": "T", "status": "done",
                                   "completedAt": "2026-08-03T10:00:00Z"}]}],
            "bugs": [{"id": "BUG-1", "status": "open",
                      "reportedAt": "2026-07-02T10:00:00Z", "taskId": "P1.1"}]})
        _mp = usage_state(proj)
        check("the populated branch derives monthlyPlan from the manifest "
              "through monthly_activity - completedAt/reportedAt/mergedAt "
              "buckets, bugsFixed via the linked done task",
              _mp["monthlyPlan"].get("2026-08", {}).get("tasksCompleted") == 1
              and _mp["monthlyPlan"].get("2026-08", {}).get("phasesMerged") == 1
              and _mp["monthlyPlan"].get("2026-07", {}).get("bugsReported") == 1
              and _mp["monthlyPlan"].get("2026-08", {}).get("bugsFixed") == 1)
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- phaseAreas (D4): the Usage tab's area filter join map ------------------
    # The client attributes spend to areas in a read-time join (row.phaseId ->
    # phase.area tags), so the map ships with the facts. Key parity again: BOTH
    # branches carry the key, and an untagged phase maps to [] rather than being
    # missing, so the client can tell "known phase, no tags" from "phase the
    # plan never heard of".
    check("usage_state ships phaseAreas in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          "phaseAreas" in _mp_empty and _mp_empty["phaseAreas"] == {})
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2},
            "phases": [
                {"id": "P1", "title": "A", "status": "done",
                 "area": ["backend", "sec"], "tasks": []},
                {"id": "P2", "title": "B", "status": "pending", "tasks": []}]})
        check("the populated branch derives phaseAreas through _areas."
              "phase_tags - a multi-tag phase keeps every tag, an untagged "
              "phase maps to [], not missing",
              usage_state(proj).get("phaseAreas")
              == {"P1": ["backend", "sec"], "P2": []})
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- areaOwners (v0.34 D3): the advisory owner per registered area ----------
    # panel.js joins UF.author against these values for the person header's
    # "owns:" line and titles the area select options. Key parity again - the
    # sibling case beside phaseAreas', because a key in one branch only is an
    # `undefined` that ships on every fresh install.
    check("usage_state ships areaOwners in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          "areaOwners" in _mp_empty and _mp_empty["areaOwners"] == {})
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2,
                     "areas": {"backend": {"root": "src",
                                           "owner": " jane@x.com "},
                               "sec": {"root": "sec", "owner": None},
                               "web": {"root": "web"}}},
            "phases": [{"id": "P1", "title": "A", "status": "done",
                        "area": ["backend", "sec"], "tasks": []}]})
        check("the populated branch maps tag -> trimmed owner through _areas."
              "registry - only tags that DECLARE a non-null owner enter the "
              "map, so null ('nobody') and undeclared read the same to the UI",
              usage_state(proj).get("areaOwners") == {"backend": "jane@x.com"})
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- report export ------------------------------------------------------------
    # There is deliberately no path parameter on /report: the location is derived
    # from the project's own config, so there is nothing to traverse with.
    _rp = tempfile.mkdtemp(prefix="panel-report-")
    try:
        os.makedirs(os.path.join(_rp, "docs", "audit"), exist_ok=True)
        with open(os.path.join(_rp, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "repo": "x"}, "phases": [
                {"id": "P1", "title": "A", "status": "done", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "done"}]}]}, fh)
        check("no report exists before it is rendered",
              os.path.isfile(report_paths(_rp)[2]) is False)
        _res = render_report(_rp)
        check("export writes the html and its markdown twin, and reports both",
              _res["ok"] and len(_res["files"]) == 2
              and any(f.endswith(".html") for f in _res["files"])
              and any(f.endswith(".md") for f in _res["files"]))
        check("everything it writes stays inside the project",
              all(_within(_rp, f) for f in _res["files"]))
        check("it hands back an in-origin href, not a filesystem path — a browser "
              "will not follow file:// from an http:// page",
              _res["href"] == "/report" and _res["exists"] is True)
    finally:
        shutil.rmtree(_rp, ignore_errors=True)
    _np = tempfile.mkdtemp(prefix="panel-noreport-")
    try:
        check("a project with no manifest refuses instead of raising",
              report_paths(_np) is None
              and render_report(_np)["ok"] is False)
    finally:
        shutil.rmtree(_np, ignore_errors=True)

    # --- routing advice ---------------------------------------------------------
    # The only server-computed metric in the Usage tab; the tab's own strings are
    # pinned in panel-server, beside UI_HTML.
    check("routing advice is shipped from the server and fails soft",
          '"routingAdvice": advice' in _src
          and "ul.routing(manifest, rows," in _src
          and "advice = []" in _src)

    # --- v0.34 C5 (lv): the data fingerprint -------------------------------------
    # Pure stats per request, folded into /api/runstatus so the existing 5s
    # poll carries it. The browser half (refreshFromDisk) is driven in
    # capture-screenshots.mjs --check.
    _fp1 = data_fingerprint(proj, read_config(proj))
    _fp2 = data_fingerprint(proj, read_config(proj))
    check("lv: the fingerprint is a pure stat - stable across two calls with "
          "nothing changed", isinstance(_fp1, str) and _fp1 and _fp1 == _fp2)
    # Change the SIZE, not only the mtime: coarse filesystems round mtime to a
    # second, and a rewrite inside that second would otherwise stamp equal.
    _m_orig = open(mpath, encoding="utf-8").read()
    try:
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(_m_orig + " ")
        check("lv: a manifest rewrite moves it",
              data_fingerprint(proj, read_config(proj)) != _fp1)
    finally:
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(_m_orig)
    _c_orig = open(_config_path(proj), encoding="utf-8").read()
    try:
        with open(_config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_c_orig + " ")
        check("lv: a config write moves it (manifestPath/ledgerDir live there, "
              "so the config file is stamped FIRST)",
              data_fingerprint(proj, read_config(proj)) != _fp1)
    finally:
        with open(_config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_c_orig)
    with open(os.path.join(led, "2026-08.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-08-03T10", "sessionId": "s9",
                             "model": "m", "msgs": 1, "in": 1, "out": 1,
                             "costUSD": 0.0}) + "\n")
    check("lv: a ledger append moves it (newest *.jsonl stat)",
          data_fingerprint(proj, read_config(proj)) != _fp1)
    # Sharded: every shard body is stamped, so a phase edit that never touches
    # the index still moves the stamp.
    _lvproj = tempfile.mkdtemp(prefix="state-lv-")
    try:
        _atomic_write_json(_config_path(_lvproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _lvm = _manifest_path(_lvproj, read_config(_lvproj))
        os.makedirs(os.path.dirname(_lvm), exist_ok=True)
        _mio.save_sharded(_lvm, {
            "meta": {"version": 3},
            "phases": [{"id": "P1", "title": "One", "status": "pending",
                        "tasks": [{"id": "P1.1", "title": "T",
                                   "status": "pending"}]}]})
        _lv1 = data_fingerprint(_lvproj, read_config(_lvproj))
        with open(os.path.join(os.path.dirname(_lvm), "phases", "P1.json"),
                  "a", encoding="utf-8") as fh:
            fh.write(" ")
        check("lv: a sharded phase body moves it without the index changing",
              data_fingerprint(_lvproj, read_config(_lvproj)) != _lv1)
    finally:
        shutil.rmtree(_lvproj, ignore_errors=True)
    _lvmiss = os.path.join(tmp, "lv-nothing-here")
    check("lv: missing everything is a stable sentinel, never a raise",
          data_fingerprint(_lvmiss, {}) == data_fingerprint(_lvmiss, {})
          and isinstance(data_fingerprint(_lvmiss, {}), str))
    check("lv: the fingerprint rides /api/runstatus's payload - with and "
          "without a manifest - so the existing poll carries it for free "
          "while it stays OUT of runStatusKey (a moved stamp hands off to "
          "refreshFromDisk instead of repainting)",
          isinstance(_run_status(proj, read_config(proj), {})
                     .get("fingerprint"), str)
          and isinstance(_run_status(_lvmiss, {}, {}).get("fingerprint"), str))
    check("lv: SSE is weighed and rejected in prose where the stamp is "
          "defined, so the next person does not re-litigate it blind",
          "SSE" in (data_fingerprint.__doc__ or ""))

    # --- v0.34 B3 (gt): the Plan gate block on /api/runstatus --------------------
    # Tier + why, bypass-armed, and the tail of the gate events feed - the
    # panel's Overview card is fed from here, so the server computes the tier
    # with the hooks' own functions rather than letting the browser guess.
    _gtcfg = _cores()[3]
    _gt = _run_status(proj, read_config(proj), {}).get("gate")
    check("gt: runstatus carries a gate block with the tier and its source",
          isinstance(_gt, dict) and _gt.get("mode") in ("observe", "warn",
                                                        "ask", "deny")
          and bool(_gt.get("source")) and isinstance(_gt.get("events"), list)
          and _gt.get("bypassArmed") is False)
    check("gt: a pinned planGate names the knob as the source, tier included",
          (_run_status(proj, {"planGate": "ask"}, {}).get("gate") or {})
          .get("mode") == "ask"
          and "planGate" in str((_run_status(proj, {"planGate": "ask"}, {})
                                 .get("gate") or {}).get("source")))
    check("gt: legacy enforce:true is named as legacy, not as evidence",
          "legacy" in str((_run_status(proj, {"enforce": True}, {})
                           .get("gate") or {}).get("source")))
    for _i in range(25):
        _gtcfg.append_gate_event(os.path.join(proj, ".claude", "logs"),
                                 {"event": "observe", "file": "f%d.ts" % _i,
                                  "sessionId": "gt"})
    _gt = _run_status(proj, read_config(proj), {}).get("gate") or {}
    check("gt: the events table is the feed's tail, newest first, capped at 20",
          len(_gt.get("events") or []) == 20
          and _gt["events"][0].get("file") == "f24.ts"
          and _gt["events"][-1].get("file") == "f5.ts")
    _gtsd = os.path.join(proj, ".claude", "state")
    os.makedirs(_gtsd, exist_ok=True)
    with open(os.path.join(_gtsd, "plan-bypass-gt.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": "t", "reason": "x",
                   "armedAtEpoch": int(time.time())}, fh)
    check("gt: a live bypass slot flips the armed indicator",
          (_run_status(proj, read_config(proj), {}).get("gate") or {})
          .get("bypassArmed") is True)
    with open(os.path.join(_gtsd, "plan-bypass-gt.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": "t", "reason": "x",
                   "armedAtEpoch": int(time.time())
                   - _gtcfg.BYPASS_TTL_SECONDS - 60}, fh)
    check("gt: an EXPIRED slot does not count as armed - the card must not "
          "claim a bypass require-plan would refuse",
          (_run_status(proj, read_config(proj), {}).get("gate") or {})
          .get("bypassArmed") is False)
    os.unlink(os.path.join(_gtsd, "plan-bypass-gt.json"))
    check("gt: a project with nothing on disk still gets a gate block, never "
          "a raise",
          isinstance(_run_status(_lvmiss, {}, {}).get("gate"), dict))

    # --- who is looking: the identity cache, in BOTH directions -----------------
    # A stale answer here is worse than a slow one: the Usage tab's "my spend"
    # filter compares this name against the ledger's `author` column, so an
    # identity that went out of date silently selects the wrong rows. Neither
    # direction is taken on trust. Every case COUNTS resolves rather than timing
    # anything — a wall-clock assertion is flaky on a loaded machine and cannot say
    # WHICH work was skipped.
    #
    # The fixture owns its whole git identity: GIT_CONFIG_NOSYSTEM plus a
    # GIT_CONFIG_GLOBAL under the temp dir, and USER/USERNAME both set (Windows
    # reads the second), so nothing about this machine's real config can decide a
    # case here — the `no-silent-pass` ambient-state rule, on the two CI platforms.
    _vtmp = tempfile.mkdtemp(prefix="state-viewer-")
    _venv_keys = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
                  "XDG_CONFIG_HOME", "USER", "USERNAME")
    _venv_saved = {k: os.environ.get(k) for k in _venv_keys}
    _real_resolve_viewer = _resolve_viewer
    _resolves = [0]

    def _counting_resolve(project, mode):
        _resolves[0] += 1
        return _real_resolve_viewer(project, mode)

    def _vwrite(path, email, settled=True):
        """Write a git config carrying one identity.

        Backdated by default because the settle guard is doing its job: a file
        written this millisecond is deliberately NOT cached, so aging it is the
        honest way to reach the cached path. `settled=False` is how the guard's
        own case reaches the other branch."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[user]\n\temail = %s\n" % email)
        if settled:
            _when = time.time() - 5
            os.utime(path, (_when, _when))

    try:
        globals()["_resolve_viewer"] = _counting_resolve
        _vproj = os.path.join(_vtmp, "proj")
        os.makedirs(_vproj)
        _vglobal = os.path.join(_vtmp, "gitconfig-global")
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        os.environ["GIT_CONFIG_GLOBAL"] = _vglobal
        os.environ["XDG_CONFIG_HOME"] = os.path.join(_vtmp, "xdg")
        os.environ["USER"] = os.environ["USERNAME"] = "fixture-user"
        os.environ.pop("GIT_CONFIG_SYSTEM", None)

        _vwrite(_vglobal, "alice@example.com")
        _resolves[0] = 0
        _v1 = _viewer(_vproj, {})
        check("viewer: the first call really does resolve — the baseline the skip "
              "case below is measured against, and the proof the counter works",
              _v1 == {"author": "alice@example.com", "mode": "email"}
              and _resolves[0] == 1)
        _resolves[0] = 0
        _v2 = _viewer(_vproj, {})
        # THE SECOND-DIRECTION CASE. It looks vacuous and it is the only one that
        # fails if invalidation becomes unconditional (a token that never compares
        # equal, a bare recompute): the answer would still be right, and the cache
        # would have bought nothing.
        check("viewer: with no identity file and no environment moved, the second "
              "call resolves NOTHING and hands back the same answer",
              _resolves[0] == 0 and _v2 == _v1)

        # THE BUG ITSELF (F-P): `git config user.email` edited under a running
        # panel. The old cache was keyed on (project, mode) and populated once, so
        # this returned alice forever.
        _vwrite(_vglobal, "bob@example.com")
        _resolves[0] = 0
        _v3 = _viewer(_vproj, {})
        check("viewer: user.email changed IN PLACE under a running process is "
              "picked up — the whole bug: no directory listing changed, so only "
              "stamping the config FILE can catch this",
              _v3["author"] == "bob@example.com" and _resolves[0] == 1)

        # The environment half. With no git identity anywhere, resolve_author's
        # answer IS $USER — a value no stat of any file could ever see move.
        _vlater = os.path.join(_vtmp, "gitconfig-later")
        os.environ["GIT_CONFIG_GLOBAL"] = _vlater          # nothing there yet
        _viewer(_vproj, {})                                # warm on the new env
        _resolves[0] = 0
        _v4 = _viewer(_vproj, {})
        check("viewer: a project whose git knows no identity falls back to the "
              "environment, and that answer caches too",
              _v4["author"] == "fixture-user" and _resolves[0] == 0)
        os.environ["USER"] = os.environ["USERNAME"] = "someone-else"
        _resolves[0] = 0
        _v5 = _viewer(_vproj, {})
        check("viewer: the environment is pinned BY VALUE - USER changed moves no "
              "file's mtime, so a stat-only token would have served the old name",
              _v5["author"] == "someone-else" and _resolves[0] == 1)

        # THE TTL-KILLER. The winning config file did not EXIST when the answer was
        # resolved, so a token covering only what was read (or a plain TTL) cannot
        # know it appeared.
        _viewer(_vproj, {})                                # re-warm, settled
        _resolves[0] = 0
        _vwrite(_vlater, "carol@example.com")
        _v6 = _viewer(_vproj, {})
        check("viewer: a config file that did not EXIST at resolve time "
              "invalidates when it appears — absent paths are stamped, never "
              "dropped from the token",
              _v6["author"] == "carol@example.com" and _resolves[0] == 1)

        # The settle guard, both ways. A case that only ever saw it accept would be
        # asserting nothing.
        _vfresh = os.path.join(_vtmp, "gitconfig-fresh")
        os.environ["GIT_CONFIG_GLOBAL"] = _vfresh
        _vwrite(_vfresh, "dave@example.com", settled=False)
        _viewer(_vproj, {})
        _resolves[0] = 0
        _v7 = _viewer(_vproj, {})
        check("viewer: an identity file written a moment ago is NOT cached — a "
              "1-second-granular mtime cannot prove the resolve saw the final "
              "bytes, and serving the pre-edit name forever is the original bug",
              _v7["author"] == "dave@example.com" and _resolves[0] == 1)
        _vsettle = time.time() - 5
        os.utime(_vfresh, (_vsettle, _vsettle))
        _viewer(_vproj, {})                                # re-warm, now settled
        _resolves[0] = 0
        _v8 = _viewer(_vproj, {})
        check("viewer: ...and the same file, once it has settled, IS cached",
              _v8["author"] == "dave@example.com" and _resolves[0] == 0)

        _vmine = _viewer(_vproj, {})
        _vmine["author"] = "clobbered"
        check("viewer: each caller gets its own copy — writing to a returned "
              "viewer cannot poison the next caller's answer",
              _viewer(_vproj, {})["author"] == "dave@example.com")

        # The watch list is what the RESOLVE read, plus what it would have read.
        # A file consulted but not stamped is precisely how a cache goes stale in
        # silence, so the two halves are checked against each other rather than
        # trusted from the docstring.
        _vwatch = _real_resolve_viewer(_vproj, "email")[1]
        check("viewer: the winning config file is in the watch list, and so is the "
              "repo config of the project and of its parent — the places a "
              "repo-local user.email can appear when the panel is opened on a "
              "subdirectory",
              _vfresh in _vwatch
              and os.path.join(os.path.realpath(_vproj), ".git", "config")
              in _vwatch
              and os.path.join(os.path.realpath(_vtmp), ".git", "config")
              in _vwatch)
        check("viewer: the origin list carries PATHS only - `--name-only`, because "
              "a plain --list also hands back every value and a git config "
              "routinely holds credential helpers and tokens",
              "--name-only" in _src.split("def _git_config_origins")[1]
              .split("def _git_config_candidates")[0])
    finally:
        globals()["_resolve_viewer"] = _real_resolve_viewer
        for _k, _v in _venv_saved.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
        shutil.rmtree(_vtmp, ignore_errors=True)

    # --- isolation cases (P12.3): the moved boundary stays real -----------------
    _imports = [l for l in _src.split("\n")
                if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server - the read side sits BELOW the "
          "server, so nothing that imports it can form a cycle",
          not any("panel_server" in l or "panel-server" in l for l in _imports))
    _panel_src = open(os.path.join(_HERE, "panel-server.py"), encoding="utf-8").read()
    _moved = ["_load", "_cores", "_defaults", "_within", "_config_path",
              "_declared_as_of", "_manifest_path", "_viewer", "_read_json",
              "read_config", "_areas_of", "_bugs_view", "_skills_of",
              "_composition_view", "areas_state", "_JOURNAL", "_journalmod",
              "JOURNAL_PAGE", "journal_state", "help_state", "help_field",
              "_policy_rules", "_policy_enforcement", "_policy_areas_view",
              "policy_state", "_active_area_tags", "_audit_lock_dir",
              "_audit_lock_held", "_lockmod", "_lock_info", "_run_status",
              "usage_state", "report_paths", "render_report", "build_state"]
    _unaliased = [n for n in _moved
                  if "\n%s = _panel_state.%s\n" % (n, n) not in _panel_src]
    check("every name this module took is aliased back in panel-server, so a route "
          "or a selftest that still spells it there resolves to THIS one: %r"
          % (_unaliased,), not _unaliased)
    _defined = [n for n in _moved if n in globals()]
    check("...and every one of them is actually defined here rather than merely "
          "expected: %r" % ([n for n in _moved if n not in globals()],),
          len(_defined) == len(_moved))
    # `_journalmod`'s memo is ONE dict, not a copy per module: the write path in
    # panel-server swaps a stub module into it and this module's `journal_state`
    # has to see the same swap, or each side would test a journal the other does
    # not have.
    check("the journal memo is shared with panel-server by identity, not copied",
          "\n_JOURNAL = _panel_state._JOURNAL\n" in _panel_src
          and isinstance(_JOURNAL, dict))

    shutil.rmtree(tmp, ignore_errors=True)

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
