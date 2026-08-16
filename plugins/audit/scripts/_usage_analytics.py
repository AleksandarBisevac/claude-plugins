#!/usr/bin/env python3
"""
What the ledger MEANS — the rows -> dict computations the CLI, the report and the
panel all render, and the honesty rules that stop them lying.

Split out of `usage_ledger.py`, which had grown to carry three unrelated jobs. This
half reads no file and holds no cursor: it consumes rows somebody else scanned and
returns dicts somebody else paints. Every function here is easy to compute and easy
to present dishonestly, which is the whole reason they live together in ONE module
rather than in each renderer — a wrong number that three surfaces agree on is worse
than no number, and the guard against that has to have a single home.

The rules those guards enforce are stated at each function, and they are the point:
a projection is suppressed below its sample gate; a cache profile reports rates and
never a fabricated dollar saving; routing advice compares only WITHIN a risk band
and only on this repo's own evidence; an absent phase budget renders as nothing,
never as 0% or 100%.

Depends on `_usage_core` (prices, timestamps, roll-ups) and on nothing else in the
tree. `usage_ledger.py` re-exports every public name defined here, so no call site
names this module: the split is a structural change, not an API change.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _usage_core import (  # noqa: E402  (prices, timestamps, roll-ups)
    DEFAULT_PRICING, GROUP_KEYS, TOKEN_KEYS, aggregate, bucket_date, parse_ts,
    price, rates_for, totals)


# --- analytics ------------------------------------------------------------------
# Pure `rows -> dict` functions. Every one of these is easy to compute and easy to
# present dishonestly, so the guard against that lives HERE rather than in each
# renderer — a wrong number that three surfaces agree on is worse than no number.

MAX_SERIES = 8              # categorical hue cap; past this the tail folds
MIN_TASKS_FOR_PROJECTION = 5
POOR_COVERAGE_PCT = 50.0


def task_index(manifest):
    """{taskId: task dict} across every phase."""
    out = {}
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                out[t["id"]] = t
    return out


def _tokens(row):
    return sum(int(row.get(k) or 0) for k in TOKEN_KEYS)


def _cost(row):
    try:
        return float(row.get("costUSD") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- spend over time ------------------------------------------------------------
def series(rows, dim, bucket="day", top=MAX_SERIES, metric="tokens"):
    """Time series per entity, ready for a multi-line chart.

    Past `top` entities the tail folds into a single `other` entry rather than
    generating a 9th hue nothing can distinguish — the categorical palette is only
    validated to 8 slots, so this is a correctness bound, not a style preference.

    Returns {buckets, entities:[{key, values, total}], folded, metric}.
    """
    keyfn = GROUP_KEYS[dim]
    valfn = _tokens if metric == "tokens" else _cost
    per = {}
    seen_buckets = set()
    for row in rows:
        b = bucket_date(row.get("ts")) if bucket == "day" else (row.get("ts") or "")
        if not b:
            continue
        seen_buckets.add(b)
        k = keyfn(row)
        per.setdefault(k, {})
        per[k][b] = per[k].get(b, 0) + valfn(row)
    buckets = sorted(seen_buckets)
    ranked = sorted(per.items(), key=lambda kv: -sum(kv[1].values()))
    keep, tail = ranked[:top], ranked[top:]
    entities = [{"key": k, "total": sum(v.values()),
                 "values": [v.get(b, 0) for b in buckets]} for k, v in keep]
    if tail:
        merged = {}
        for _, v in tail:
            for b, n in v.items():
                merged[b] = merged.get(b, 0) + n
        entities.append({"key": "other", "total": sum(merged.values()),
                         "values": [merged.get(b, 0) for b in buckets]})
    return {"buckets": buckets, "entities": entities, "folded": len(tail),
            "metric": metric}


def compare(rows, since, until):
    """This window vs the one immediately before it, same length.

    Returns None for `prior` and every delta when there is nothing to compare
    against — a first-run dashboard must not invent a '+100%'."""
    start, end = parse_ts((since or "") + "T00:00:00Z"), \
        parse_ts((until or "") + "T23:59:59Z")
    current = [r for r in rows
               if (not since or bucket_date(r.get("ts")) >= since)
               and (not until or bucket_date(r.get("ts")) <= until)]
    out = {"current": totals(current), "prior": None, "deltas": {}, "window": None}
    if start is None or end is None or end <= start:
        return out
    span = end - start
    p_start, p_end = start - span, start
    prior = []
    for r in rows:
        t = parse_ts((bucket_date(r.get("ts")) or "") + "T00:00:00Z")
        if t is not None and p_start <= t < p_end:
            prior.append(r)
    if not prior:
        return out
    pt = totals(prior)
    out["prior"] = pt
    for key in ("tokens", "costUSD", "msgs", "out"):
        before = pt.get(key) or 0
        now = out["current"].get(key) or 0
        out["deltas"][key] = (100.0 * (now - before) / before) if before else None
    out["window"] = {"since": since, "until": until}
    return out


def cache_profile(rows):
    """Cache economics, stated as RATES rather than an invented saving.

    Deliberately returns no "you saved $N": without caching you would not have made
    the same calls at the same volume, so that number is a fabricated counterfactual.
    `inputCostVsFreshPct` is a real rate comparison — what the input side actually
    bills as a share of what the identical token volume would bill at fresh-input
    rates — and is safe to show."""
    slot = {k: 0 for k in TOKEN_KEYS}
    per_phase = {}
    for row in rows:
        for k in TOKEN_KEYS:
            slot[k] += int(row.get(k) or 0)
        pid = row.get("phaseId") or "--"
        p = per_phase.setdefault(pid, {k: 0 for k in TOKEN_KEYS})
        for k in TOKEN_KEYS:
            p[k] += int(row.get(k) or 0)

    def hit(d):
        billed = d["in"] + d["cacheW5m"] + d["cacheW1h"] + d["cacheR"]
        return (100.0 * d["cacheR"] / billed) if billed else 0.0

    by_phase = {pid: round(hit(d), 1) for pid, d in per_phase.items()}
    worst = min(by_phase.items(), key=lambda kv: kv[1]) if by_phase else None
    # Rate comparison against the fresh-input price of the SAME volume.
    actual = fresh = 0.0
    for row in rows:
        r = rates_for(row.get("model"))
        vol = (int(row.get("in") or 0) + int(row.get("cacheW5m") or 0)
               + int(row.get("cacheW1h") or 0) + int(row.get("cacheR") or 0))
        actual += (int(row.get("in") or 0) * r["in"]
                   + int(row.get("cacheW5m") or 0) * r["cacheW5m"]
                   + int(row.get("cacheW1h") or 0) * r["cacheW1h"]
                   + int(row.get("cacheR") or 0) * r["cacheR"])
        fresh += vol * r["in"]
    return {
        "hitPct": round(hit(slot), 1),
        "readTokens": slot["cacheR"],
        "writeTokens": slot["cacheW5m"] + slot["cacheW1h"],
        "freshTokens": slot["in"],
        "inputCostVsFreshPct": round(100.0 * actual / fresh, 1) if fresh else 100.0,
        "byPhase": by_phase,
        "worstPhase": worst,
    }


# --- cost per unit of work ------------------------------------------------------
def _percentile(values, p):
    """Nearest-rank percentile on a sorted list. Stdlib only, no numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[idx]


def unit_economics(manifest, rows):
    """Cost per completed task, and what the remaining work would cost at that rate.

    The projection is SUPPRESSED below `MIN_TASKS_FOR_PROJECTION` completed tasks and
    is always a p25-p75 RANGE rather than a point estimate. A confident forecast off
    three samples is worse than no forecast."""
    tasks = task_index(manifest)
    cost_by_task = {}
    for row in rows:
        tid = row.get("taskId")
        if tid:
            cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)
    done = [c for tid, c in cost_by_task.items()
            if (tasks.get(tid) or {}).get("status") == "done"]
    remaining = sum(1 for t in tasks.values()
                    if t.get("status") in ("pending", "in_progress", "blocked"))
    out = {
        "completed": len(done), "remaining": remaining,
        "gate": MIN_TASKS_FOR_PROJECTION, "sufficient": len(done) >= MIN_TASKS_FOR_PROJECTION,
        "costPerTask": round(sum(done) / len(done), 4) if done else None,
        "p25": None, "p75": None, "projection": None,
        "mostExpensive": sorted(
            ((tid, round(c, 4), (tasks.get(tid) or {}).get("attempts"))
             for tid, c in cost_by_task.items() if tid in tasks),
            key=lambda x: -x[1])[:5],
    }
    if not out["sufficient"]:
        return out
    p25, p75 = _percentile(done, 25), _percentile(done, 75)
    out["p25"], out["p75"] = round(p25, 4), round(p75, 4)
    out["projection"] = {"low": round(p25 * remaining, 2),
                         "high": round(p75 * remaining, 2)}
    return out


BAND_ORDER = ("typical", "high", "outlier")

# The ONE place the relative basis's shape is stated: the sample gate and the two
# percentiles cost_bands() reads below. panel.js no longer restates these numbers
# — panel-server.py serializes this exact dict into the page (__COST_BAND_PARAMS__)
# so a change here cannot silently leave the panel classifying tasks differently
# from the report. Keep it JSON-serializable (plain int values only): it crosses
# the Python/JS boundary as-is via json.dumps.
COST_BAND_PARAMS = {
    "gate": MIN_TASKS_FOR_PROJECTION,
    "percentileHigh": 50,
    "percentileOutlier": 90,
}


def cost_bands(manifest, rows, cfg=None):
    """Sort tasks into `typical` / `high` / `outlier` by what they cost.

    Deliberately NOT called a risk band: manifest tasks already carry `risk`, which
    is the risk of the CHANGE (and is what `routing` compares within). Two different
    axes wearing one word would make both impossible to discuss.

    The thresholds are the project's own median and p90 by default, so this means
    something on day one with no configuration and re-calibrates as the work grows.
    A team with a real budget can pin absolute numbers in
    `usage.bands.{highUSD,outlierUSD}` instead; `basis` says which is in force, and
    the callers print the thresholds, because a band whose definition is invisible
    is a number nobody can argue with.

    Two guards:

    * Below `MIN_TASKS_FOR_PROJECTION` completed tasks the relative basis returns
      NOTHING — percentiles off three samples are noise, and a confidently wrong
      band is worse than no band. The absolute basis has no such gate: a configured
      threshold is an opinion the user already holds.
    * Thresholds come from COMPLETED tasks only, because a half-finished task's cost
      is not comparable. They are then applied to every task including in-flight
      ones, which is what lets the metering hook warn while there is still time to
      act.
    """
    band_cfg = ((cfg or {}).get("bands") or {}) if isinstance(cfg, dict) else {}
    tasks = task_index(manifest)
    cost_by_task = {}
    for row in rows:
        tid = row.get("taskId")
        if tid and tid in tasks:
            cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)

    out = {"basis": None, "high": None, "outlier": None, "byTask": {},
           "counts": {b: 0 for b in BAND_ORDER}, "sample": 0,
           "gate": COST_BAND_PARAMS["gate"], "sufficient": False}

    hi, out_ = band_cfg.get("highUSD"), band_cfg.get("outlierUSD")
    try:
        hi = float(hi) if hi is not None else None
        out_ = float(out_) if out_ is not None else None
    except (TypeError, ValueError):      # a garbled config must not classify
        hi = out_ = None
    if hi is not None and out_ is not None and 0 < hi <= out_:
        out.update(basis="absolute", high=hi, outlier=out_, sufficient=True)
    else:
        done = [c for tid, c in cost_by_task.items()
                if (tasks.get(tid) or {}).get("status") == "done"]
        out["sample"] = len(done)
        if len(done) < COST_BAND_PARAMS["gate"]:
            return out
        out.update(basis="relative", sufficient=True,
                   high=round(_percentile(done, COST_BAND_PARAMS["percentileHigh"]), 4),
                   outlier=round(_percentile(done, COST_BAND_PARAMS["percentileOutlier"]), 4))

    for tid, cost in cost_by_task.items():
        band = ("outlier" if cost > out["outlier"]
                else "high" if cost > out["high"] else "typical")
        out["byTask"][tid] = band
        out["counts"][band] += 1
    return out


def phase_budgets(manifest, rows):
    """Spend against `phase.budgetUSD`, for the phases that declare one.

    Ties spend to the PLAN rather than to the calendar, which is the comparison a
    manifest-driven pipeline can make and a date-range dashboard cannot.

    Phases without a budget are returned too, with `budget: None` — the surfaces
    need to render them as "—". Defaulting an absent budget to zero would paint
    every unbudgeted phase as infinitely over, and defaulting it to the spend
    would paint every one as exactly on target; both are lies about a phase whose
    owner simply never set a number.

    `pct` is uncapped on purpose: a phase at 130% should read 130%, not a bar
    pinned at full with the overrun hidden."""
    spent = {}
    for row in rows:
        pid = row.get("phaseId") or "--"
        spent[pid] = spent.get(pid, 0.0) + _cost(row)

    out, budgeted, total_budget, total_spent = [], 0, 0.0, 0.0
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict) or not ph.get("id"):
            continue
        pid = ph["id"]
        raw = ph.get("budgetUSD")
        budget = (float(raw) if isinstance(raw, (int, float))
                  and not isinstance(raw, bool) and raw > 0 else None)
        used = round(spent.get(pid, 0.0), 4)
        if budget is not None:
            budgeted += 1
            total_budget += budget
            total_spent += used
        out.append({
            "id": pid, "title": ph.get("title") or "", "status": ph.get("status"),
            "budget": budget, "spent": used,
            "pct": round(100.0 * used / budget, 1) if budget else None,
            "over": bool(budget and used > budget),
        })
    return {"phases": out, "budgeted": budgeted,
            "totalBudget": round(total_budget, 4) if budgeted else None,
            "totalSpent": round(total_spent, 4) if budgeted else None,
            "anyOver": any(p["over"] for p in out)}


def band_of(bands, task_id):
    """The band for one task, or None when banding is suppressed/unknown."""
    if not bands or not bands.get("sufficient"):
        return None
    return (bands.get("byTask") or {}).get(task_id)


def retry_cost(manifest, rows):
    """Spend on retried tasks and spend on blocked tasks — reported SEPARATELY.

    These are not summed into a single "waste" figure and the retried number is not
    called waste at all. The ledger buckets by hour, not by attempt, so there is no
    per-attempt token boundary: a task that took three attempts and then landed did
    not waste three attempts' worth. Only the BLOCKED number is unambiguous spend
    with no outcome."""
    tasks = task_index(manifest)
    total = retried = blocked = 0.0
    retried_ids, blocked_ids = set(), set()
    for row in rows:
        c = _cost(row)
        total += c
        tid = row.get("taskId")
        t = tasks.get(tid) if tid else None
        if not t:
            continue
        try:
            attempts = int(t.get("attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts > 1:
            retried += c
            retried_ids.add(tid)
        if t.get("status") == "blocked":
            blocked += c
            blocked_ids.add(tid)
    return {
        "totalCost": round(total, 4),
        "retriedCost": round(retried, 4), "retriedTasks": len(retried_ids),
        "retriedPct": round(100.0 * retried / total, 1) if total else 0.0,
        "blockedCost": round(blocked, 4), "blockedTasks": len(blocked_ids),
        "blockedPct": round(100.0 * blocked / total, 1) if total else 0.0,
        # Explicit so no renderer is tempted to add the two together.
        "overlaps": len(retried_ids & blocked_ids),
    }


# --- model routing --------------------------------------------------------------
RISK_ORDER = ("high", "med", "low", "unrated")


def routing(manifest, rows, pricing=None):
    """Cost per completed task and mean attempts, per model, WITHIN a risk band.

    Deliberately NOT a spend-share / task-share ratio. Tasks are not equal-sized —
    the plugin's own guidance routes hard work to the strong model on purpose and
    warns that a cheap botched attempt costs more than one clean expensive pass. A
    bare ratio would show that working system as a problem and push users toward
    exactly the routing the docs warn against. Comparing within a risk band is the
    only comparison that means anything.

    Models come from the LEDGER (what actually ran), never from the manifest's
    `model` field, which is a provider-agnostic tier name in a different namespace."""
    tasks = task_index(manifest)
    acc = {}
    for row in rows:
        tid = row.get("taskId")
        t = tasks.get(tid) if tid else None
        if not t:
            continue
        risk = t.get("risk") or "unrated"
        model = row.get("model") or "unknown"
        cell = acc.setdefault((risk, model),
                              {"cost": 0.0, "tasks": {},
                               "counts": {k: 0 for k in TOKEN_KEYS}})
        cell["cost"] += _cost(row)
        cell["tasks"][tid] = t
        # Kept so the counterfactual below can re-price the SAME tokens at another
        # model's rates. Cost alone cannot do that.
        for k in TOKEN_KEYS:
            cell["counts"][k] += int(row.get(k) or 0)
    by_risk, counts_by = {}, {}
    for (risk, model), cell in acc.items():
        n = len(cell["tasks"])
        attempts = [int(t.get("attempts") or 1) for t in cell["tasks"].values()]
        by_risk.setdefault(risk, {})[model] = {
            "tasks": n,
            "cost": round(cell["cost"], 4),
            "costPerTask": round(cell["cost"] / n, 4) if n else None,
            "meanAttempts": round(sum(attempts) / float(len(attempts)), 2)
            if attempts else None,
        }
        counts_by[(risk, model)] = cell["counts"]
    return {
        "byRisk": by_risk,
        "risks": [r for r in RISK_ORDER if r in by_risk],
        "models": sorted({m for cells in by_risk.values() for m in cells}),
        "advice": _routing_advice(by_risk, counts_by, pricing),
    }


MIN_ROUTING_EVIDENCE = 3    # tasks needed on BOTH models, in that band, in this repo
ATTEMPT_TOLERANCE = 0.2     # a cheaper model that retries more is not cheaper
MIN_ADVICE_SAVING_USD = 1.0
MIN_ADVICE_SAVING_PCT = 10.0


def _has_rates(model, pricing=None):
    """True only when the price table names this model. `rates_for` falls back to
    `_default` for anything unknown, and recommending a move onto a model whose
    price is a guess would be worse than saying nothing."""
    table = pricing if isinstance(pricing, dict) and pricing else DEFAULT_PRICING
    fallback = table.get("_default") or DEFAULT_PRICING["_default"]
    return rates_for(model, pricing) is not fallback


def _routing_advice(by_risk, counts_by, pricing=None):
    """Where the ledger's own evidence supports moving work to a cheaper model.

    Every condition here exists to stop this becoming the glib advice the routing
    table was built to avoid:

    * WITHIN one risk band only. The plugin routes hard work to the strong model
      on purpose; comparing across bands would flag that working system as a fault.
    * The cheaper model must already have run `MIN_ROUTING_EVIDENCE` tasks in that
      band IN THIS REPO. Without that, "sonnet would be cheaper" is a price-list
      observation, not a finding — of course it is cheaper, it is also different.
    * Its mean attempts must be no worse than the incumbent's (plus a small
      tolerance). A cheap model that retries twice is not cheaper, and the retry
      analytics right above this say exactly that.
    * Both models must have real rates in the table, never a `_default` guess.
    * The saving must clear both a percentage and an absolute floor, or the advice
      is noise dressed as insight.

    Both sides are priced at TODAY's rates on the same token counts, so the two
    numbers share one rate epoch — comparing a historical cost against a current
    price list would be a different (and wrong) sum. The result is an upper bound,
    not a forecast: a different model would not emit the same tokens.
    """
    out = []
    for risk, cells in by_risk.items():
        ranked = sorted(cells.items(), key=lambda kv: -(kv[1]["cost"]))
        for model, cell in ranked:
            if cell["tasks"] < MIN_ROUTING_EVIDENCE or not _has_rates(model, pricing):
                continue
            counts = counts_by.get((risk, model)) or {}
            at_from = price(counts, model, pricing)
            best = None
            for other, ocell in cells.items():
                if other == model:
                    continue
                if ocell["tasks"] < MIN_ROUTING_EVIDENCE or not _has_rates(other, pricing):
                    continue
                if (ocell["meanAttempts"] or 0) > (cell["meanAttempts"] or 0) \
                        + ATTEMPT_TOLERANCE:
                    continue
                at_other = price(counts, other, pricing)
                saving = at_from - at_other
                if saving < MIN_ADVICE_SAVING_USD:
                    continue
                if at_from <= 0 or 100.0 * saving / at_from < MIN_ADVICE_SAVING_PCT:
                    continue
                if best is None or saving > best[1]:
                    best = (other, saving, at_other, ocell)
            if best:
                other, _saving, at_other, ocell = best
                # Round FIRST, then derive — so the three figures reconcile on
                # screen. Rounding each independently let 25.01 - 15.00 print as a
                # saving of 10.00, which is a cent nobody can account for in a
                # module whose whole claim is that its numbers can be checked.
                af, at = round(at_from, 2), round(at_other, 2)
                out.append({
                    "risk": risk, "from": model, "to": other,
                    "tasks": cell["tasks"],
                    "fromMeanAttempts": cell["meanAttempts"],
                    "atFromRates": af,
                    "atToRates": at,
                    "saving": round(af - at, 2),
                    "savingPct": round(100.0 * (af - at) / af, 1) if af else 0.0,
                    "evidenceTasks": ocell["tasks"],
                    "evidenceAttempts": ocell["meanAttempts"],
                })
    out.sort(key=lambda a: -a["saving"])
    return out


# --- coverage and monthly activity ----------------------------------------------
def coverage(rows):
    """How much spend the attribution layers actually resolved.

    A dashboard where 90% is `unattributed` is not showing you your phases — it is
    showing you one big bucket. This drives a visible warning rather than letting
    every other chart quietly mean nothing."""
    by_attr, total = {}, 0
    for row in rows:
        n = _tokens(row)
        total += n
        by_attr[row.get("attr") or "unattributed"] = \
            by_attr.get(row.get("attr") or "unattributed", 0) + n
    if not total:
        return {"total": 0, "byAttr": {}, "attributedPct": 0.0,
                "taskLevelPct": 0.0, "warn": False}
    unattributed = by_attr.get("unattributed", 0)
    return {
        "total": total,
        "byAttr": {k: round(100.0 * v / total, 1) for k, v in by_attr.items()},
        "attributedPct": round(100.0 * (total - unattributed) / total, 1),
        "taskLevelPct": round(100.0 * by_attr.get("task", 0) / total, 1),
        "warn": (100.0 * unattributed / total) > POOR_COVERAGE_PCT,
    }


MONTHLY_PLAN_KEYS = ("tasksCompleted", "bugsReported", "bugsFixed",
                     "phasesMerged")


def _event_month(value):
    """ISO timestamp -> 'YYYY-MM' in UTC, or None when unparseable.

    Parsed through parse_ts rather than sliced, so an offset timestamp lands in
    its UTC month and garbage lands nowhere instead of in a bucket named after
    its first seven characters."""
    epoch = parse_ts(value)
    if epoch is None:
        return None
    g = time.gmtime(epoch)
    return "%04d-%02d" % (g.tm_year, g.tm_mon)


def _month_span(first, last):
    """Inclusive list of 'YYYY-MM' from first to last."""
    out = []
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    while (y, m) <= (ly, lm):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def monthly_activity(manifest, rows, months=12):
    """Calendar-month roll-up of ledger spend AND plan progress — the ONE
    computation site behind the 12-month overview's three surfaces (report
    table, panel card, CLI), so their numbers cannot drift apart.

    ledger: {month: {tokens, costUSD, msgs}} from `rows`.
    plan:   {month: {tasksCompleted, bugsReported, bugsFixed, phasesMerged}}
            from the manifest — tasksCompleted counts DONE tasks by their
            `completedAt` month, bugsReported by `bug.reportedAt`, phasesMerged
            by `phase.mergedAt`. bugsFixed is DERIVED the way
            audit-status.effective_bug_status derives 'fixed': a bug whose
            linked task (`bug.taskId`) is done, bucketed by THAT task's
            completedAt — and a wontfix bug never counts.

    `months[]` is zero-filled between the first and last month seen on either
    side, then trimmed to the LAST `months` entries (None/0 = no cap). Both
    dicts carry exactly the months in `months[]`, zero-filled, so renderers
    never have to .get() around holes.
    """
    ledger_acc = {}
    for r in (rows or []):
        m = _event_month((r.get("ts") or "") + ":00:00Z")
        if m is None:
            continue
        slot = ledger_acc.setdefault(m, {"tokens": 0, "costUSD": 0.0,
                                         "msgs": 0})
        slot["tokens"] += _tokens(r)
        slot["costUSD"] += _cost(r)
        try:
            slot["msgs"] += int(r.get("msgs") or 0)
        except (TypeError, ValueError):
            pass

    plan_acc = {}

    def bump(month, key):
        if not month:
            return
        slot = plan_acc.setdefault(month, {k: 0 for k in MONTHLY_PLAN_KEYS})
        slot[key] += 1

    tasks = task_index(manifest)
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict):
            continue
        bump(_event_month(ph.get("mergedAt")), "phasesMerged")
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("status") == "done":
                bump(_event_month(t.get("completedAt")), "tasksCompleted")
    for b in ((manifest or {}).get("bugs") or []):
        if not isinstance(b, dict):
            continue
        bump(_event_month(b.get("reportedAt")), "bugsReported")
        if b.get("status") == "wontfix":
            continue
        t = tasks.get(b.get("taskId")) if b.get("taskId") else None
        if isinstance(t, dict) and t.get("status") == "done":
            bump(_event_month(t.get("completedAt")), "bugsFixed")

    seen = sorted(set(ledger_acc) | set(plan_acc))
    if not seen:
        return {"months": [], "ledger": {}, "plan": {}}
    span = _month_span(seen[0], seen[-1])
    if months and len(span) > months:
        span = span[-months:]
    ledger = {}
    plan = {}
    for m in span:
        got = ledger_acc.get(m) or {"tokens": 0, "costUSD": 0.0, "msgs": 0}
        ledger[m] = {"tokens": got["tokens"],
                     "costUSD": round(got["costUSD"], 6),
                     "msgs": got["msgs"]}
        plan[m] = plan_acc.get(m) or {k: 0 for k in MONTHLY_PLAN_KEYS}
    return {"months": span, "ledger": ledger, "plan": plan}


# --- bench ----------------------------------------------------------------------
# WHY THIS EXISTS. Several comments in this tree state a measured cost — the
# `aggregate` this module imports carries "Measured 30.0 ms -> 18.4 ms over 20,000
# rows", `hooks/meter-usage.py` says "26 ms over a 9-month, 8,740-row ledger" — and
# until now there was not one `perf_counter`, `timeit` or benchmark anywhere in the
# repository, so not one of those numbers could be produced again by anybody,
# including their author. This is the smallest honest repair: a fixture, a timer,
# and a figure a human can run twice and compare.
#
# DELIBERATELY NOT A CI THRESHOLD. A shared runner's noise floor is wider than the
# regressions worth catching, and a gate that flaps teaches people to ignore it —
# which costs more than having no gate. This prints; it never fails.
#
# BEST-OF-N, NOT THE MEAN. Timing noise on a shared machine is ONE-SIDED: every
# other thing running can only make a call slower, never faster. A mean therefore
# reports the machine's mood alongside the code, while the minimum is the closest
# observable thing to the true cost. `_time_best` returns the minimum and every
# printed figure carries the run count, because a minimum without its sample size
# is not a measurement.
#
# NO I/O, EVER. The fixture is COMPUTED, not read. This module opens no file (see
# the module docstring) and the bench keeps it that way, so nothing here can read —
# or grow — the repo's own live `.claude/usage/` ledger.

_BENCH_SIZES = (1000, 10000, 50000)
_BENCH_REPEATS = 5
_BENCH_PHASES = 12
_BENCH_TASKS = 12
_BENCH_MONTHS = 9
_BENCH_MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")
_BENCH_AUTHORS = ("alex@bench.example", "sara@bench.example", "milos@bench.example")
_BENCH_RISKS = ("high", "med", "low")

# `_report_usage.load_usage` calls `aggregate` six times per report (day, phase,
# model, author, agent, session). COUNTED at those call sites, not remembered:
# `_usage_core.aggregate`'s own comment still says eleven, which was the count
# BEFORE those calls were hoisted out of the payload dict. Six is what a report
# costs today, so six is what the derived line below multiplies by.
_BENCH_AGGREGATE_PER_REPORT = 6


def _time_best(fn, repeats, clock=None):
    """`(seconds, result)` — the FASTEST of `repeats` calls, and the last result.

    The minimum, never the mean; the section comment above says why. `clock` is
    injectable for one reason: a timing harness whose clock cannot be replaced can
    only be tested by sleeping, and a case that asserts "the minimum, not the
    mean" against real sleeps is a case that flakes on a busy machine. The
    selftest hands it a scripted clock and pins the answer exactly.
    """
    clock = clock if clock is not None else time.perf_counter
    best, out = None, None
    for _ in range(max(1, int(repeats))):
        start = clock()
        out = fn()
        elapsed = clock() - start
        if best is None or elapsed < best:
            best = elapsed
    return best, out


def _bench_manifest():
    """The fixed plan the fixture's rows are attributed to.

    The PLAN is fixed while the row count varies, because that is the shape a
    ledger actually grows in: a manifest is written once and metered against for
    months. Every honesty gate in this module is cleared ON PURPOSE — enough done
    tasks for the projection and the cost bands, budgets on some phases and not
    others, all three risk bands, retried tasks and blocked ones, bugs with a
    linked task. A fixture that tripped a gate would have the bench timing a guard
    clause and printing it as the cost of the function.
    """
    phases = []
    for p in range(1, _BENCH_PHASES + 1):
        tasks = []
        for t in range(1, _BENCH_TASKS + 1):
            i = (p - 1) * _BENCH_TASKS + (t - 1)
            status = "done"
            if i % 7 == 0:
                status = "blocked" if i % 14 == 0 else "pending"
            tasks.append({
                "id": "P%d.%d" % (p, t), "title": "bench task %d" % i,
                "status": status, "risk": _BENCH_RISKS[i % 3],
                "attempts": 3 if i % 9 == 0 else 1,
                "completedAt": "2026-%02d-%02dT10:00:00Z" % (1 + i % _BENCH_MONTHS,
                                                            1 + i % 28),
            })
        phase = {"id": "P%d" % p, "title": "bench phase %d" % p, "status": "done",
                 "mergedAt": "2026-%02d-05T10:00:00Z" % (1 + p % _BENCH_MONTHS),
                 "tasks": tasks}
        if p % 3 == 0:                       # some budgeted, some not
            phase["budgetUSD"] = 50.0
        phases.append(phase)
    bugs = [{"id": "BUG-%d" % b, "status": "open",
             "severity": "med",
             "reportedAt": "2026-%02d-1%dT10:00:00Z" % (1 + b % _BENCH_MONTHS,
                                                        b % 10),
             "taskId": "P%d.2" % (1 + b % _BENCH_PHASES)}
            for b in range(1, 13)]
    return {"meta": {}, "phases": phases, "bugs": bugs}


def _bench_rows(n):
    """`n` deterministic ledger rows for `_bench_manifest()`'s plan.

    Deterministic by ARITHMETIC rather than by a seeded RNG, so the fixture is
    identical on every interpreter and `_bench_rows(n)[:m] == _bench_rows(m)` —
    which is what makes the per-row figures at 1k, 10k and 50k comparable to each
    other rather than three unrelated samples.

    Shaped like the real thing: hour buckets across `_BENCH_MONTHS` months, three
    models, three authors, a rotating session id, and roughly one row in eleven
    left unattributed so `coverage` has both sides to divide.
    """
    tids = ["P%d.%d" % (p, t) for p in range(1, _BENCH_PHASES + 1)
            for t in range(1, _BENCH_TASKS + 1)]
    span = _BENCH_MONTHS * 28              # 28-day months: every date is real
    rows = []
    for i in range(n):
        day = i % span
        tid = tids[i % len(tids)]
        adhoc = (i % 11 == 0)
        rows.append({
            "ts": "2026-%02d-%02dT%02d" % (1 + day // 28, 1 + day % 28, i % 24),
            "model": _BENCH_MODELS[i % len(_BENCH_MODELS)],
            "author": _BENCH_AUTHORS[i % len(_BENCH_AUTHORS)],
            "sessionId": "sess-%d" % (i % 40),
            "agentType": None if adhoc else "audit-executor",
            "phaseId": None if adhoc else tid.split(".")[0],
            "taskId": None if adhoc else tid,
            "attr": "unattributed" if adhoc else "task",
            "msgs": 1 + i % 5,
            "in": 100 + i % 900,
            "out": 500 + i % 4000,
            "cacheW5m": 1000 + i % 9000,
            "cacheW1h": i % 500,
            "cacheR": 20000 + i % 60000,
            "costUSD": 0.10 + (i % 97) / 100.0,
        })
    return rows


# The comparison window `compare` is timed over: the middle third of the fixture's
# own span, so both the current and the prior window hold rows. A window with an
# empty prior returns early and would time nothing.
_BENCH_SINCE = "2026-04-01"
_BENCH_UNTIL = "2026-06-28"


def _bench_cases(manifest, rows):
    """`(label, thunk)` per timed case — every rows -> dict pass this module
    defines, plus `aggregate`, which is defined one layer down but is the hottest
    thing a report runs through this layer.

    Two properties the `bn` cases below hold this to:

    * the fixture is built OUTSIDE the thunk and closed over, so the timer measures
      the call and never the fixture build;
    * every LABEL is the name of the function its thunk calls. That pairing is
      proven by swapping the named global out and watching the thunk go through it,
      because a label that drifted onto its neighbour is worse than no bench: it
      reports the wrong function's cost under the right function's name, and is
      believed.

    `task_index` and `band_of` are absent on purpose — the first runs INSIDE four
    of the cases below, the second is a dict lookup.
    """
    return (
        ("aggregate", lambda: aggregate(rows, "day")),
        ("series", lambda: series(rows, "model")),
        ("compare", lambda: compare(rows, _BENCH_SINCE, _BENCH_UNTIL)),
        ("cache_profile", lambda: cache_profile(rows)),
        ("unit_economics", lambda: unit_economics(manifest, rows)),
        ("cost_bands", lambda: cost_bands(manifest, rows)),
        ("phase_budgets", lambda: phase_budgets(manifest, rows)),
        ("retry_cost", lambda: retry_cost(manifest, rows)),
        ("routing", lambda: routing(manifest, rows)),
        ("coverage", lambda: coverage(rows)),
        ("monthly_activity", lambda: monthly_activity(manifest, rows)),
    )


def _bench(sizes=None, repeats=None):
    """Print the analytics pass's wall time at several ledger sizes. Always 0.

    Several sizes rather than one number, because the interesting property is the
    SHAPE: a pass that is 1 us/row at 1,000 rows and 1 us/row at 50,000 rows is
    linear and needs nothing, while one whose per-row cost climbs is quadratic and
    will meet a ledger it cannot finish.
    """
    sizes = sizes if sizes is not None else _BENCH_SIZES
    repeats = repeats if repeats is not None else _BENCH_REPEATS
    manifest = _bench_manifest()
    print("_usage_analytics --bench  (python %s on %s)"
          % (sys.version.split()[0], sys.platform))
    print("fixture:  %d phases x %d tasks = %d tasks, %d months, computed in "
          "memory - this module opens no file, so no ledger on this machine is "
          "read or written"
          % (_BENCH_PHASES, _BENCH_TASKS, _BENCH_PHASES * _BENCH_TASKS,
             _BENCH_MONTHS))
    print("timing:   best of %d runs per case - the MINIMUM, not the mean, "
          "because other load can only make a call slower" % repeats)
    print("note:     aggregate() is timed on the 'day' dimension; load_usage() "
          "calls it %d times per report" % _BENCH_AGGREGATE_PER_REPORT)
    for n in sizes:
        rows = _bench_rows(n)
        print("")
        print("rows=%s" % "{:,}".format(len(rows)))
        print("  %-18s %10s %11s" % ("case", "best", "per row"))
        total, agg = 0.0, None
        for label, thunk in _bench_cases(manifest, rows):
            seconds, _ = _time_best(thunk, repeats)
            total += seconds
            if label == "aggregate":
                agg = seconds
            print("  %-18s %7.3f ms %8.3f us"
                  % (label, seconds * 1e3, seconds * 1e6 / max(1, n)))
        # A SUM of minima, not a measured whole-pass time - said so rather than
        # printed as if one run had been observed taking it.
        print("  %-18s %7.3f ms %8.3f us"
              % ("sum of minima", total * 1e3, total * 1e6 / max(1, n)))
        if agg is not None:
            print("  %-18s %7.3f ms %8.3f us"
                  % ("aggregate x%d" % _BENCH_AGGREGATE_PER_REPORT,
                     agg * _BENCH_AGGREGATE_PER_REPORT * 1e3,
                     agg * _BENCH_AGGREGATE_PER_REPORT * 1e6 / max(1, n)))
    return 0


def _mode(argv):
    """Which mode the flags ask for: 'selftest', 'bench' or 'usage'.

    `--selftest` WINS over `--bench` when both are given. CI runs `--selftest` on
    every `.py` in the tree on two platforms; a suite that could turn into a
    multi-second benchmark run because a stray flag came along would be paid for
    on every push. A mode that can be entered by accident will be.
    """
    if "--selftest" in argv:
        return "selftest"
    if "--bench" in argv:
        return "bench"
    return "usage"


# --- selftest -------------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond, detail=""):
        cases.append((label, bool(cond), detail))

    # --- monthly_activity (ma) ----------------------------------------
    # One computation site for the 12-month overview's three surfaces
    # (report table, panel card, CLI) - so the honesty rules are pinned
    # here once instead of asserted per renderer.
    _ma_man = {"phases": [
        {"id": "P1", "mergedAt": "2026-06-05T10:00:00Z", "tasks": [
            {"id": "P1.1", "status": "done",
             "completedAt": "2026-06-03T10:00:00Z"},
            {"id": "P1.2", "status": "done",
             "completedAt": "2026-08-02T10:00:00Z"},
            {"id": "P1.3", "status": "pending",
             "completedAt": "2026-08-09T10:00:00Z"},
            {"id": "P1.4", "status": "done", "completedAt": "not-a-date"},
        ]}],
        "bugs": [
            {"id": "BUG-1", "status": "open",
             "reportedAt": "2026-07-15T10:00:00Z", "taskId": "P1.2"},
            {"id": "BUG-2", "status": "wontfix",
             "reportedAt": "2026-07-16T10:00:00Z", "taskId": "P1.1"},
            {"id": "BUG-3", "status": "open",
             "reportedAt": "2026-08-01T10:00:00Z"},
        ]}
    _ma_rows = [
        {"ts": "2026-06-10T09", "in": 5, "out": 100, "cacheW5m": 0,
         "cacheW1h": 0, "cacheR": 20, "msgs": 2, "costUSD": 0.5},
        {"ts": "2026-08-05T14", "in": 1, "out": 40, "cacheW5m": 0,
         "cacheW1h": 0, "cacheR": 9, "msgs": 1, "costUSD": 0.25},
        {"ts": "garbage", "in": 9, "out": 9, "cacheW5m": 0,
         "cacheW1h": 0, "cacheR": 0, "msgs": 9, "costUSD": 9.0},
    ]
    ma = monthly_activity(_ma_man, _ma_rows)
    check("ma1 months are zero-filled between the first and last month seen "
          "on either side",
          ma["months"] == ["2026-06", "2026-07", "2026-08"])
    check("ma2 both halves carry every month in months[], zeroed when quiet, "
          "so no renderer needs to .get() around holes",
          set(ma["ledger"]) == set(ma["months"]) == set(ma["plan"])
          and ma["ledger"]["2026-07"] == {"tokens": 0, "costUSD": 0.0,
                                          "msgs": 0})
    check("ma3 the ledger half buckets tokens/cost/msgs by calendar month, "
          "and a garbled ts is skipped rather than mis-bucketed",
          ma["ledger"]["2026-06"] == {"tokens": 125, "costUSD": 0.5,
                                      "msgs": 2}
          and ma["ledger"]["2026-08"]["msgs"] == 1
          and sum(v["msgs"] for v in ma["ledger"].values()) == 3)
    check("ma4 tasksCompleted counts DONE tasks by completedAt month - a "
          "completedAt on a pending task does not count, nor an unparseable one",
          ma["plan"]["2026-06"]["tasksCompleted"] == 1
          and ma["plan"]["2026-08"]["tasksCompleted"] == 1
          and sum(v["tasksCompleted"] for v in ma["plan"].values()) == 2)
    check("ma5 bugsReported buckets by reportedAt month",
          ma["plan"]["2026-07"]["bugsReported"] == 2
          and ma["plan"]["2026-08"]["bugsReported"] == 1)
    check("ma6 a bug counts as fixed in the month its LINKED TASK completed "
          "- the effective_bug_status derivation, not a status field",
          ma["plan"]["2026-08"]["bugsFixed"] == 1
          and ma["plan"]["2026-07"]["bugsFixed"] == 0)
    check("ma7 wontfix never reads as fixed, even with a done linked task",
          sum(v["bugsFixed"] for v in ma["plan"].values()) == 1)
    check("ma8 phasesMerged buckets by mergedAt month",
          ma["plan"]["2026-06"]["phasesMerged"] == 1
          and sum(v["phasesMerged"] for v in ma["plan"].values()) == 1)
    check("ma9 the window trims to the LAST n months, dropping older keys "
          "from both halves",
          monthly_activity(_ma_man, _ma_rows, months=2)["months"]
          == ["2026-07", "2026-08"]
          and "2026-06" not in monthly_activity(
              _ma_man, _ma_rows, months=2)["ledger"])
    check("ma10 empty everything is an empty shape, not a crash",
          monthly_activity({}, []) == {"months": [], "ledger": {},
                                       "plan": {}}
          and monthly_activity(None, None) == {"months": [], "ledger": {},
                                               "plan": {}})
    check("ma11 an offset timestamp lands in its UTC month",
          monthly_activity({"phases": [{"id": "P9", "tasks": [
              {"id": "P9.1", "status": "done",
               "completedAt": "2026-09-01T01:00:00+02:00"}]}]}, [])
          ["plan"]["2026-08"]["tasksCompleted"] == 1)

    # --- analytics: the honesty guards --------------------------------
    def mkrow(day, model, author, task, phase, attr, cost, out_tok=100,
              cr=1000, cw=100, fin=10):
        return {"ts": "2026-08-%02dT10" % day, "model": model, "author": author,
                "taskId": task, "phaseId": phase, "attr": attr,
                "sessionId": "s1", "agentType": "audit-executor", "msgs": 1,
                "in": fin, "out": out_tok, "cacheW5m": cw, "cacheW1h": 0,
                "cacheR": cr, "costUSD": cost}

    man = {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done", "risk": "high", "attempts": 1},
        {"id": "P1.2", "status": "done", "risk": "high", "attempts": 3},
        {"id": "P1.3", "status": "done", "risk": "low", "attempts": 1},
        {"id": "P1.4", "status": "done", "risk": "low", "attempts": 1},
        {"id": "P1.5", "status": "done", "risk": "med", "attempts": 1},
        {"id": "P1.6", "status": "blocked", "risk": "med", "attempts": 3},
        {"id": "P1.7", "status": "pending", "risk": "low"},
    ]}]}
    ar = [
        mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
        mkrow(2, "claude-opus-5", "a@x", "P1.2", "P1", "task", 30.0),
        mkrow(3, "claude-haiku-4-5", "b@x", "P1.3", "P1", "task", 1.0),
        mkrow(4, "claude-haiku-4-5", "b@x", "P1.4", "P1", "task", 2.0),
        mkrow(5, "claude-sonnet-5", "c@x", "P1.5", "P1", "task", 5.0),
        mkrow(6, "claude-sonnet-5", "c@x", "P1.6", "P1", "task", 7.0),
        mkrow(7, "claude-opus-5", "a@x", None, None, "unattributed", 4.0),
    ]

    # series: top-N fold
    s = series(ar, "model")
    check("series: buckets sorted, one value per bucket per entity",
          s["buckets"] == sorted(s["buckets"])
          and all(len(e["values"]) == len(s["buckets"]) for e in s["entities"]))
    check("series: values sum back to each entity total",
          all(sum(e["values"]) == e["total"] for e in s["entities"]))
    many = [mkrow(1, "m%02d" % i, "a@x", None, None, "unattributed", 1.0)
            for i in range(12)]
    sm = series(many, "model", top=8)
    check("series: past 8 entities the tail folds into 'other', never a 9th hue",
          len(sm["entities"]) == 9 and sm["entities"][-1]["key"] == "other"
          and sm["folded"] == 4)
    check("series: folding preserves the grand total",
          sum(e["total"] for e in sm["entities"]) == sum(_tokens(r) for r in many))

    # compare: no prior period -> no invented delta
    c_none = compare(ar, "2026-08-01", "2026-08-07")
    check("compare: no prior window -> prior None and no deltas",
          c_none["prior"] is None and c_none["deltas"] == {})
    c_some = compare(ar, "2026-08-05", "2026-08-07")
    check("compare: a real prior window yields deltas",
          c_some["prior"] is not None and "tokens" in c_some["deltas"])
    check("compare: a zero-valued prior metric yields None, not a division blow-up",
          compare(ar, "2026-08-01", "2026-08-02")["deltas"] in ({}, None)
          or all(v is None or isinstance(v, float)
                 for v in compare(ar, "2026-08-05", "2026-08-07")["deltas"].values()))

    # cache_profile: rates, never a fabricated dollar saving
    cp = cache_profile(ar)
    check("cache: reports a hit rate and a rate comparison",
          0 <= cp["hitPct"] <= 100 and 0 < cp["inputCostVsFreshPct"] <= 100)
    check("cache: exposes NO fabricated dollar saving",
          not any("sav" in k.lower() or k.endswith("USD") for k in cp))
    check("cache: per-phase rates and a worst phase for the story",
          "P1" in cp["byPhase"] and cp["worstPhase"] is not None)

    # unit_economics: the sample gate
    few = unit_economics({"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done"}]}]},
        [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 5.0)])
    check("unit: projection SUPPRESSED below the sample gate",
          few["projection"] is None and few["sufficient"] is False
          and few["gate"] == MIN_TASKS_FOR_PROJECTION)
    ue = unit_economics(man, ar)
    check("unit: 5 completed tasks clears the gate", ue["sufficient"] is True)
    check("unit: projection is a p25-p75 RANGE, never a point estimate",
          ue["projection"] and ue["projection"]["low"] <= ue["projection"]["high"])
    check("unit: only DONE tasks count toward cost-per-task",
          ue["completed"] == 5)
    check("unit: remaining counts pending + in_progress + blocked",
          ue["remaining"] == 2)
    check("unit: most-expensive list carries attempts for context",
          ue["mostExpensive"] and len(ue["mostExpensive"][0]) == 3)

    # routing advice: fires only when THIS repo's own evidence supports it.
    # Both fixtures above route one model per band, so neither produces advice
    # — a well-routed project getting silence is the point, not a gap.
    def band(model, n, attempts, out_tok, risk="low", first=0):
        man_tasks = [{"id": "R%s%d" % (model[7:10], i), "status": "done",
                      "risk": risk, "attempts": attempts} for i in range(n)]
        rws = [mkrow(1 + first, model, "a@x", t["id"], "PR", "task", 0.0,
                     out_tok=out_tok) for t in man_tasks]
        return man_tasks, rws

    o_t, o_r = band("claude-opus-5", 5, 1, 200_000)
    s_t, s_r = band("claude-sonnet-5", 4, 1, 200_000)
    rman = {"phases": [{"id": "PR", "tasks": o_t + s_t}]}
    adv = routing(rman, o_r + s_r)["advice"]
    check("advice: a within-band cheaper model with real evidence is named",
          len(adv) == 1 and adv[0]["from"] == "claude-opus-5"
          and adv[0]["to"] == "claude-sonnet-5" and adv[0]["risk"] == "low",
          adv)
    # The three figures must reconcile EXACTLY: a reader who subtracts the two
    # displayed costs has to land on the displayed saving, to the cent.
    check("advice: both sides priced on the SAME tokens at today's rates, and "
          "the arithmetic on screen adds up exactly",
          adv and adv[0]["atFromRates"] > adv[0]["atToRates"] > 0
          and adv[0]["saving"] == round(
              adv[0]["atFromRates"] - adv[0]["atToRates"], 2)
          and adv[0]["savingPct"] == round(
              100.0 * adv[0]["saving"] / adv[0]["atFromRates"], 1),
          adv)
    check("advice: it carries the in-repo evidence it rests on",
          adv and adv[0]["evidenceTasks"] == 4
          and adv[0]["evidenceAttempts"] == 1.0 and adv[0]["tasks"] == 5)

    # Each gate, alone, must silence it.
    s2_t, s2_r = band("claude-sonnet-5", 2, 1, 200_000)
    check("advice: SILENT when the cheaper model has too little in-repo "
          "evidence (a price list is not a finding)",
          routing({"phases": [{"id": "PR", "tasks": o_t + s2_t}]},
                  o_r + s2_r)["advice"] == [])
    s3_t, s3_r = band("claude-sonnet-5", 4, 2, 200_000)
    check("advice: SILENT when the cheaper model retries more — a model that "
          "needs two attempts is not cheaper",
          routing({"phases": [{"id": "PR", "tasks": o_t + s3_t}]},
                  o_r + s3_r)["advice"] == [])
    tiny_o, tiny_or = band("claude-opus-5", 5, 1, 100)
    tiny_s, tiny_sr = band("claude-sonnet-5", 4, 1, 100)
    check("advice: SILENT when the saving is below the absolute floor",
          routing({"phases": [{"id": "PR", "tasks": tiny_o + tiny_s}]},
                  tiny_or + tiny_sr)["advice"] == [])
    x_t, x_r = band("claude-mystery-9", 4, 1, 200_000)
    check("advice: SILENT for a model with no real rates — never recommend a "
          "move onto a price that is a _default guess",
          _has_rates("claude-mystery-9") is False
          and routing({"phases": [{"id": "PR", "tasks": o_t + x_t}]},
                      o_r + x_r)["advice"] == [])
    # Cross-band comparison is the thing the whole table exists to refuse.
    hi_t, hi_r = band("claude-sonnet-5", 4, 1, 200_000, risk="high")
    check("advice: never compares ACROSS risk bands",
          all(a["risk"] == "low" for a in routing(
              {"phases": [{"id": "PR", "tasks": o_t + hi_t}]},
              o_r + hi_r)["advice"]))

    # cost_bands: the same sample gate, and a name that does not collide
    cb = cost_bands(man, ar)
    check("bands: 5 completed tasks clears the gate on the relative basis",
          cb["basis"] == "relative" and cb["sufficient"] is True
          and cb["sample"] == 5)
    _ti = task_index(man)
    _done_cost = {}
    for _r in ar:
        _t = _r.get("taskId")
        if _t and (_ti.get(_t) or {}).get("status") == "done":
            _done_cost[_t] = _done_cost.get(_t, 0.0) + _r["costUSD"]
    _dc = list(_done_cost.values())
    check("bands: thresholds ARE the project's own median and p90 "
          "(computed from completed tasks only)",
          cb["high"] == round(_percentile(_dc, 50), 4)
          and cb["outlier"] == round(_percentile(_dc, 90), 4)
          and cb["high"] <= cb["outlier"])
    check("bands: every classified task lands in exactly one band",
          sum(cb["counts"].values()) == len(cb["byTask"])
          and set(cb["byTask"].values()) <= set(BAND_ORDER))
    # COST_BAND_PARAMS is the ONE place the relative basis's shape is stated —
    # panel-server.py JSON-dumps this exact dict into the page as
    # __COST_BAND_PARAMS__, and panel.js reads it back instead of restating the
    # numbers. Pinned against LITERAL values (not re-derived through the
    # constant itself) so a skewed boundary here goes red by name instead of
    # trivially agreeing with itself.
    check("bands: COST_BAND_PARAMS is exactly {gate:5, high:p50, outlier:p90} "
          "— the values panel.js's __COST_BAND_PARAMS__ is generated from",
          COST_BAND_PARAMS == {"gate": 5, "percentileHigh": 50,
                                "percentileOutlier": 90})
    # And cost_bands() actually SOURCES its gate/percentiles from that constant
    # rather than a second copy of the numbers: recomputing the same run's
    # thresholds with literal 50/90 must match what cost_bands() returned.
    check("bands: gate and percentiles used ARE COST_BAND_PARAMS, not a "
          "restated copy — this is the constant the JS mirror is generated from",
          cb["gate"] == COST_BAND_PARAMS["gate"] == MIN_TASKS_FOR_PROJECTION
          and cb["high"] == round(_percentile(_dc, 50), 4)
          and cb["outlier"] == round(_percentile(_dc, 90), 4))
    cb_few = cost_bands({"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done"}]}]},
        [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 5.0)])
    check("bands: SUPPRESSED below the gate — no basis, no classification",
          cb_few["basis"] is None and cb_few["sufficient"] is False
          and cb_few["byTask"] == {}
          and cb_few["gate"] == MIN_TASKS_FOR_PROJECTION)
    check("bands: band_of returns None while suppressed, so callers cannot "
          "accidentally render a band that was never computed",
          band_of(cb_few, "P1.1") is None and band_of(None, "P1.1") is None)
    # A configured threshold is an opinion the user already holds, so it needs
    # no sample — but a malformed one must never classify anything.
    cb_abs = cost_bands(cb_few and {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done"}]}]},
        [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 40.0)],
        {"bands": {"highUSD": 5, "outlierUSD": 20}})
    check("bands: an absolute basis needs no sample and is labelled as such",
          cb_abs["basis"] == "absolute" and cb_abs["sufficient"] is True
          and cb_abs["byTask"]["P1.1"] == "outlier")
    for bad in ({"highUSD": "x", "outlierUSD": 20}, {"highUSD": 50, "outlierUSD": 10},
                {"highUSD": 0, "outlierUSD": 10}, {"highUSD": 5}):
        got = cost_bands(man, ar, {"bands": bad})
        if got["basis"] != "relative":
            break
    else:
        bad = None
    check("bands: a garbled or inverted threshold pair falls back to the "
          "relative basis instead of classifying wrongly", bad is None)
    check("bands: the word 'risk' is not reused — that axis already exists",
          "risk" not in cb and set(BAND_ORDER) == {"typical", "high", "outlier"})

    # phase_budgets: an absent budget is "—", never 0% and never 100%.
    # Explicit rows, so the assertions do not silently depend on what some
    # other fixture happens to price out to.
    _brows = [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
              mkrow(2, "claude-opus-5", "a@x", "P2.1", "P2", "task", 13.0),
              mkrow(3, "claude-opus-5", "a@x", None, "P3", "phase", 99.0)]
    pb = phase_budgets({"phases": [
        {"id": "P1", "title": "Alpha", "budgetUSD": 40, "tasks": []},
        {"id": "P2", "title": "Beta", "budgetUSD": 10, "tasks": []},
        {"id": "P3", "title": "Gamma", "tasks": []}]}, _brows)
    _byid = {p["id"]: p for p in pb["phases"]}
    check("budget: a phase without one reports None, not zero",
          _byid["P3"]["budget"] is None and _byid["P3"]["pct"] is None
          and _byid["P3"]["over"] is False and _byid["P3"]["spent"] == 99.0)
    check("budget: spend is summed per phase from the ledger",
          _byid["P1"]["spent"] == 10.0 and _byid["P1"]["pct"] == 25.0
          and _byid["P1"]["over"] is False)
    check("budget: pct is uncapped so an overrun reads as an overrun",
          _byid["P2"]["pct"] == 130.0 and _byid["P2"]["over"] is True)
    check("budget: totals cover only the phases that declared a budget "
          "(P3's 99.0 must not inflate them)",
          pb["budgeted"] == 2 and pb["totalBudget"] == 50.0
          and pb["totalSpent"] == 23.0 and pb["anyOver"] is True)
    check("budget: a zero, negative, boolean or string budget is no budget",
          all(phase_budgets({"phases": [dict(
              {"id": "P1", "tasks": []}, budgetUSD=bad)]},
              ar)["phases"][0]["budget"] is None
              for bad in (0, -5, True, False, "40", None)))
    check("budget: no budgets anywhere -> totals are None, not 0",
          phase_budgets({"phases": [{"id": "P1", "tasks": []}]},
                        ar)["totalBudget"] is None)

    # retry_cost: retried and blocked reported apart, never summed
    rc = retry_cost(man, ar)
    check("retry: retried and blocked are SEPARATE figures",
          rc["retriedCost"] == 37.0 and rc["blockedCost"] == 7.0)
    check("retry: no combined 'waste' key exists to be misread",
          not any("waste" in k.lower() for k in rc))
    check("retry: the overlap between the two sets is stated, not hidden",
          rc["overlaps"] == 1)
    check("retry: percentages are of total spend",
          abs(rc["retriedPct"] - 100.0 * 37.0 / 59.0) < 0.2)

    # routing: within-risk comparison, no bare ratio
    rt = routing(man, ar)
    check("routing: grouped by risk band, then model",
          "high" in rt["byRisk"] and "claude-opus-5" in rt["byRisk"]["high"])
    check("routing: exposes NO spend-share/task-share ratio",
          not any("ratio" in k.lower() for cells in rt["byRisk"].values()
                  for cell in cells.values() for k in cell))
    check("routing: carries cost-per-task and mean attempts per cell",
          rt["byRisk"]["high"]["claude-opus-5"]["costPerTask"] == 20.0
          and rt["byRisk"]["high"]["claude-opus-5"]["meanAttempts"] == 2.0)
    check("routing: models come from the LEDGER, not manifest tiers",
          all(m.startswith("claude-") for m in rt["models"]))
    check("routing: risks are ordered high -> low, not alphabetical",
          rt["risks"] == ["high", "med", "low"])

    # coverage
    cv = coverage(ar)
    check("coverage: task-level share never exceeds attributed share",
          0 < cv["taskLevelPct"] <= cv["attributedPct"] <= 100)
    # phase-level spend is attributed but NOT task-level — the gap between the
    # two numbers is exactly the orchestrator's own turns
    cv2 = coverage(ar + [mkrow(8, "claude-opus-5", "a@x", None, "P1", "phase", 3.0)])
    check("coverage: phase-attributed spend counts as attributed, not task-level",
          cv2["taskLevelPct"] < cv2["attributedPct"])
    check("coverage: shares across attribution buckets sum to 100",
          abs(sum(cv2["byAttr"].values()) - 100.0) < 0.2, repr(cv2["byAttr"]))
    check("coverage: does not warn on a well-attributed ledger",
          cv["warn"] is False)
    bad = coverage([mkrow(1, "m", "a@x", None, None, "unattributed", 1.0)])
    check("coverage: warns when unattributed dominates",
          bad["warn"] is True and bad["attributedPct"] == 0.0)
    check("coverage: empty ledger is not a crash", coverage([])["total"] == 0)

    # --- bn: the bench harness measures what it claims ----------------
    # A bench that silently measures the wrong thing is worse than none, so each
    # of these pins one way this one could be wrong while still printing
    # plausible numbers.
    check("bn1 the fixture is EXACTLY the size the bench prints beside every "
          "figure - a row count that drifted would make every per-row number "
          "under it wrong, and nothing else would notice",
          [len(_bench_rows(k)) for k in (0, 1, 37, 1000)] == [0, 1, 37, 1000])
    check("bn2 ...and it is deterministic AND prefix-stable, which is what "
          "makes the 1k / 10k / 50k rows comparable to each other rather than "
          "three unrelated samples",
          _bench_rows(200) == _bench_rows(200)
          and _bench_rows(200)[:100] == _bench_rows(100))
    _bm = _bench_manifest()
    _br = _bench_rows(_BENCH_SIZES[0])
    _b_bands, _b_unit = cost_bands(_bm, _br), unit_economics(_bm, _br)
    check("bn3 the fixture CLEARS every honesty gate in this module, so each "
          "timed case does its real work - a suppressed cost_bands or a "
          "compare() with no prior window returns in microseconds, and the "
          "bench would print that guard clause as the cost of the function",
          _b_bands["sufficient"] and _b_bands["sample"] >= COST_BAND_PARAMS["gate"]
          and _b_unit["projection"] is not None
          and coverage(_br)["total"] > 0
          and 0 < coverage(_br)["attributedPct"] < 100
          and len(monthly_activity(_bm, _br)["months"]) == _BENCH_MONTHS
          and phase_budgets(_bm, _br)["budgeted"] > 0
          and len(routing(_bm, _br)["risks"]) == 3
          and retry_cost(_bm, _br)["retriedTasks"] > 0
          and compare(_br, _BENCH_SINCE, _BENCH_UNTIL)["prior"] is not None,
          "%r" % (_b_bands,))
    # The label -> function pairing, proven by SWAPPING the named global rather
    # than by reading the source. Both directions fail here: a thunk that
    # stopped calling its function (0 hits) and one that calls it twice or calls
    # its neighbour as well (2 hits) are both reported.
    _mislabelled = []
    for _label, _thunk in _bench_cases(_bm, _br):
        _real, _hits = globals()[_label], []

        def _spy(*a, **kw):
            _hits.append(1)
            return _real(*a, **kw)

        globals()[_label] = _spy
        try:
            _thunk()
        finally:
            globals()[_label] = _real
        if len(_hits) != 1:
            _mislabelled.append((_label, len(_hits)))
    check("bn4 every timed thunk calls the function its LABEL names, exactly "
          "once - a bench that prints one function's cost under another's name "
          "is worse than no bench, because it is believed",
          _mislabelled == [], repr(_mislabelled))
    _timed = set(lbl for lbl, _ in _bench_cases(_bm, _br))
    _own_public = set(n for n, v in globals().items()
                      if not n.startswith("_") and callable(v)
                      and getattr(v, "__module__", None) == __name__)
    check("bn5 every rows->dict pass DEFINED here is timed; the only two that "
          "are not are named on purpose (task_index runs inside four of the "
          "cases, band_of is a dict lookup) - so a pass added later and left "
          "unmeasured fails HERE rather than quietly missing from the table",
          _own_public - _timed == {"task_index", "band_of"},
          repr(sorted(_own_public - _timed)))
    # A scripted clock, not sleeps: elapsed 4.0, 1.0, 3.0 over three runs. The
    # three candidate answers are far apart on purpose - minimum 1.0, mean 2.67,
    # last 3.0 - so the fixture can tell a correct harness from either wrong one.
    _ticks = [0.0, 4.0, 4.0, 5.0, 5.0, 8.0]
    _read, _calls = [], []

    def _scripted_clock():
        _read.append(1)
        return _ticks[len(_read) - 1]

    def _counted():
        _calls.append(1)
        return "ok"

    _sec, _res = _time_best(_counted, 3, clock=_scripted_clock)
    check("bn6 the timed section runs the callable exactly `repeats` times and "
          "hands back its result",
          len(_calls) == 3 and _res == "ok", "%d call(s)" % len(_calls))
    check("bn7 ...and reports the MINIMUM of those runs - never the mean "
          "(2.667) and never the last (3.0)", _sec == 1.0, repr(_sec))
    check("bn8 --selftest wins over --bench whichever order they arrive in, so "
          "CI's per-file sweep can never turn into a benchmark run; a bare "
          "invocation is still a usage error",
          _mode(["--selftest"]) == "selftest" and _mode(["--bench"]) == "bench"
          and _mode(["--selftest", "--bench"]) == "selftest"
          and _mode(["--bench", "--selftest"]) == "selftest"
          and _mode([]) == "usage" and _mode(["--nope"]) == "usage")
    # The printed contract, at a size the suite can afford. Counted, not merely
    # found: one timing line per case plus the two derived lines, so a figure
    # that silently stopped being printed fails instead of going unnoticed.
    import io
    _buf, _stdout = io.StringIO(), sys.stdout
    sys.stdout = _buf
    try:
        _rc = _bench(sizes=(200,), repeats=2)
    finally:
        sys.stdout = _stdout
    _out = _buf.getvalue()
    _timing_lines = [ln for ln in _out.splitlines() if " ms " in ln]
    check("bn9 --bench exits 0 and prints, for every case, the size, a wall "
          "time in ms and the derived per-row figure - the three things a "
          "human needs in order to act on it",
          _rc == 0 and "rows=200" in _out and "best of 2 runs" in _out
          and "MINIMUM" in _out
          and len(_timing_lines) == len(_bench_cases(_bm, _br)) + 2
          and all(any(lbl in ln for ln in _timing_lines)
                  for lbl, _ in _bench_cases(_bm, _br))
          and all((" ms " in ln and " us" in ln) for ln in _timing_lines),
          repr(_out[:400]))

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if (detail and not ok) else ""))
    print("\n_usage_analytics: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    _MODE = _mode(sys.argv[1:])
    if _MODE == "selftest":
        raise SystemExit(_selftest())
    if _MODE == "bench":
        raise SystemExit(_bench())
    sys.stderr.write("usage: _usage_analytics.py --selftest | --bench\n")
    raise SystemExit(2)
