#!/usr/bin/env python3
"""
The Usage tab's payload: the ledger folded into compact positional facts the
browser re-aggregates, plus the small slice of plan the analytics need.

Split out of `_panel_state.py` (U3.1). Layer 4: `_panel_paths` at 3, and it
runtime-loads `usage_ledger` at 3.

Stdlib only, Python 3.8 compatible.
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

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (meta.areas registry + shared resolution)
import _panel_paths as _paths  # noqa: E402  (the shared base, at layer 3)

# Carried by module-level alias so every body below reads exactly as it did in
# `_panel_state`, where these were siblings rather than imports.
_load = _paths._load
_declared_as_of = _paths._declared_as_of
_manifest_path = _paths._manifest_path
read_config = _paths.read_config


# --- the Usage tab's payload ------------------------------------------------------
# WHY THIS IS A SET OF PIECES AND NOT ONE FUNCTION. `usage_state` had two returns
# -- an `empty` dict for the no-data path and a populated one at the end -- and
# they spelled the SAME eighteen keys twice with nothing comparing them. A key
# added to one and forgotten in the other is an `undefined` in the panel that
# appears only on a repo with no ledger yet: only on a FRESH INSTALL, i.e. only
# for a new user and never for anyone in a position to notice it. Three of the
# cases in tests/ (monthlyPlan, phaseAreas, areaOwners) exist because that
# happened three times, and each of them pins ONE key by name. `_usage_shape` is
# the general answer: both branches now return it, so the two cannot disagree by
# construction rather than by three cases and a comment.
_MAX_FACTS = 20000

# The positional columns of a `facts` row, in order. The client reads its rows
# against this list, so the two travel together in the payload.
_FACT_FIELDS = ("ts", "phase", "task", "model", "author", "agent", "attr",
                "tokens", "cost", "msgs")


def _usage_shape(**overrides):
    """The /api/usage payload: ONE key list, with what an empty project gets.

    Every branch of `usage_state` returns this, so "the key set" is a thing that
    exists in one place instead of being an agreement between two dict literals.
    `counts` comes from `_ledger_counts([])` rather than a second literal of its
    own -- the same eight keys were also spelled twice, one level down.

    RAISES on an override this shape has no key for, and that is the point: a
    typo'd override (`phaseTitle` for `phaseTitles`) is exactly the defect this
    function exists to make impossible, and silently accepting it would put the
    key back in one branch only. The overrides are spelled in this file, never
    derived from data, so the only way to reach the raise is an edit -- which
    the suite fails on before it can ship.

    The dict is rebuilt per call on purpose: a module-level template would hand
    every caller the SAME `{}` for `phaseTitles`, and one caller writing to a
    payload it was handed would poison the next request's.
    """
    shape = {
        "enabled": True,
        "ledgerDir": "",
        "showCost": True,
        "pricingAsOf": None,
        "pricingAsOfDeclared": False,
        "facts": [],
        # Empty on the no-ledger path even though the populated branch ships the
        # ten column names: there are no rows to read against them. Same KEY,
        # different value -- which is the distinction that matters to a client
        # reading `payload.fields.length`.
        "fields": [],
        "phaseTitles": {},
        "taskMeta": {},
        "phaseBudgets": {},
        "routingAdvice": [],
        "monthlyPlan": {},
        "phaseAreas": {},
        "areaOwners": {},
        "bands": {},
        "counts": _ledger_counts([]),
        "rolled": False,
        "totalRows": 0,
    }
    unknown = sorted(k for k in overrides if k not in shape)
    if unknown:
        raise KeyError(
            "_usage_shape(): %s is not a key of the /api/usage payload. Add it "
            "to the shape above -- adding it here only would put it in one "
            "branch, which is the `undefined` on a fresh install this function "
            "exists to prevent." % ", ".join(repr(k) for k in unknown))
    shape.update(overrides)
    return shape


def _ledger_counts(rows):
    """The orientation counts for the tab's context line.

    Computed over the WHOLE ledger on purpose -- they describe the shape of the
    data you are looking at, not the current filter. `sessionId` is counted here
    and deliberately never enters `facts`, where it would multiply row
    cardinality for a number shown once.

    `_ledger_counts([])` is the empty answer, which is why `_usage_shape` calls
    it for its default instead of writing the same eight keys a second time.
    """
    days = sorted({(r.get("ts") or "")[:10] for r in rows} - {""})
    return {
        "phases": len({r.get("phaseId") for r in rows if r.get("phaseId")}),
        "tasks": len({r.get("taskId") for r in rows if r.get("taskId")}),
        "models": len({r.get("model") for r in rows if r.get("model")}),
        "authors": len({r.get("author") for r in rows if r.get("author")}),
        "sessions": len({r.get("sessionId") for r in rows if r.get("sessionId")}),
        "days": len(days),
        "from": days[0] if days else None,
        "to": days[-1] if days else None,
    }


def _usage_facts(rows, token_keys, rolled):
    """`(facts, seen)` -- ledger rows folded onto the fact key, then flattened.

    FACTS RATHER THAN FINISHED TABLES: compact positional arrays the browser
    re-aggregates on every filter change, so switching model/author/phase/range
    is instant and never round-trips. `rolled` folds the timestamp to a DAY
    instead of an hour, which is what keeps the payload bounded on a long-lived
    ledger; the caller reports that it happened rather than truncating silently.

    `seen` is counted here rather than taken as `len(rows)` because it is the
    number of ledger rows that reached the fold, and a future filter in this
    loop would make the two differ without anything saying so.
    """
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
        slot[0] += sum(int(r.get(k) or 0) for k in token_keys)
        slot[1] += float(r.get("costUSD") or 0.0)
        slot[2] += int(r.get("msgs") or 0)
    return ([list(k) + [v[0], round(v[1], 6), v[2]]
             for k, v in sorted(facts.items())], seen)


def _usage_manifest_slice(manifest):
    """`(titles, task_meta, budgets)` -- the small slice of plan the analytics need.

    Shipped so EVERY panel recomputes client-side under the current filter. The
    alternative (server-computed metrics) would leave half the tab silently
    ignoring the filter bar, which is worse than a slightly larger payload.

    `titles`/`budgets` are per-PHASE and must cover a phase with no tasks (it
    still has a name and can still declare a budget), so that half stays a phase
    walk; the task half is `_mio.iter_tasks`. Three id-keyed dicts, so the split
    costs nothing: the same document order still decides the same last-wins
    winner it did when the two walks were nested.

    All three reset together on a shape surprise -- a half-built slice would let
    the tab label some tasks and not others with no way to tell which happened.
    """
    titles, task_meta, budgets = {}, {}, {}
    try:
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
                # The RECORDED count, zero included, and `null` when the task
                # records nothing - the same three answers
                # `_usage_routing.recorded_attempts` gives, because the panel's
                # JavaScript computes the same mean from this field and the two
                # must agree. `or 1` here reported one attempt for every task the
                # manifest says has none, which is what `audit-task.py` writes for
                # every new one. The budget field two lines up already makes this
                # distinction ("non-numeric all mean no budget, never a budget of
                # zero") - in the opposite direction, and for the same reason.
                _att = t.get("attempts")
                if isinstance(_att, bool) or not isinstance(_att, int):
                    _att = None
                task_meta[t["id"]] = {
                    "status": t.get("status"), "risk": t.get("risk") or "unrated",
                    "attempts": _att,
                    "title": t.get("title") or ""}
    except Exception:
        return ({}, {}, {})
    return (titles, task_meta, budgets)


def _usage_derived(ul, manifest, rows, ucfg):
    """The four blocks that need the assembled MANIFEST, keyed by payload key.

    Returned as payload keys so the caller hands them straight to `_usage_shape`
    and no name is spelled twice on the way. Each is independently fail-soft:
    one of these going wrong must cost the tab that one card, never the tab.
    """
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

    return {"routingAdvice": advice, "monthlyPlan": monthly_plan,
            "phaseAreas": phase_areas, "areaOwners": area_owners}


def usage_state(project):
    """Payload for the Usage tab.

    Ships FACTS rather than finished tables — compact positional arrays the browser
    re-aggregates on every filter change, so switching model/author/phase/range is
    instant and never round-trips. Beyond _MAX_FACTS hourly rows the facts are rolled
    up to daily first, which keeps the payload bounded on a long-lived ledger; the
    response says so via `rolled` rather than silently truncating.

    THE THREE EXITS ALL GO THROUGH `_usage_shape`, which is the whole reason the
    pieces above exist: an unreadable ledger, an empty one and a populated one
    cannot ship different key sets, because none of them writes a dict literal.

    Read-only: no lock, no writes, nothing that can collide with a running phase."""
    cfg_mod = _paths.hooks_config()
    config = read_config(project)
    ucfg = cfg_mod.usage_cfg(config)
    ledger_dir = str(cfg_mod.ledger_dir(project, config))
    # What the CONFIG says, which is answerable with no ledger at all and so is
    # true of every exit below.
    declared = {"enabled": bool(ucfg.get("enabled", True)),
                "ledgerDir": ledger_dir,
                "showCost": bool(ucfg.get("showCost", True)),
                "pricingAsOf": ucfg.get("pricingAsOf"),
                "pricingAsOfDeclared": _declared_as_of(config),
                "bands": ucfg.get("bands") or {}}
    try:
        ul = _load("audit_usage_ledger", "usage_ledger.py")
        rows = ul.read_ledger(ledger_dir)
    except Exception:
        return _usage_shape(**declared)
    if not rows:
        return _usage_shape(**declared)

    rolled = len(rows) > _MAX_FACTS
    facts, seen = _usage_facts(rows, ul.TOKEN_KEYS, rolled)
    # ONE read for the five consumers below. They each used to call
    # `load_manifest_safe(mpath)` for themselves, which on a sharded manifest is
    # 1 index + 1 file per phase EVERY TIME: measured at 100 file opens and 5 JSON
    # parse passes for a 19-phase plan, per GET /api/usage, to answer five
    # questions about one document. Reading once is also the more correct answer:
    # five reads could straddle a concurrent manifest write and ship five
    # mutually inconsistent views of it. It sits outside every guard because
    # `load_manifest_safe` is TOTAL -- it returns {} on any error and never
    # raises -- so the try blocks below still cover exactly what they covered
    # before the hoist: the CONSUMERS, not the read.
    manifest = _mio.load_manifest_safe(_manifest_path(project, config))
    titles, task_meta, budgets = _usage_manifest_slice(manifest)

    payload = dict(declared)
    payload.update(_usage_derived(ul, manifest, rows, ucfg))
    payload.update({"fields": list(_FACT_FIELDS), "facts": facts,
                    "phaseTitles": titles, "taskMeta": task_meta,
                    "phaseBudgets": budgets, "counts": _ledger_counts(rows),
                    "rolled": rolled, "totalRows": seen})
    return _usage_shape(**payload)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_usage.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__panel_usage.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
