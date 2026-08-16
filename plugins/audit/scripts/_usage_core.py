#!/usr/bin/env python3
"""
Prices, timestamps and roll-ups — the arithmetic every other usage module stands on.

Split out of `usage_ledger.py` because the two halves above it (the transcript
scanner in `usage_ledger.py`, the presentation analytics in `_usage_analytics.py`)
both need this and neither needs the other. Nothing here reads a file, spawns a
process or knows what a transcript is: every function takes values and returns
values, which is why this file's cases need no fixture directory at all.

Three things live here, and the reason each is HERE rather than beside its caller:

  pricing      - a rate table and the cost of a bag of tokens. `hooks/_config.py`
                 keeps its own copy (hooks may import nothing from scripts/) and
                 `pricing_divergences()` is what keeps the two honest.
  timestamps   - one ISO parse and one hour-bucket rule. Two parsers would be two
                 answers to 'which hour did this land in', and the ledger's whole
                 shape is that bucket.
  aggregation  - `totals` / `aggregate` / `aggregate_area` / `heatmap`, the
                 roll-ups the CLI, the report and the panel all read. One home, so
                 three surfaces cannot disagree about a number.

`usage_ledger.py` re-exports every public name defined here, so no call site names
this module: the split is a structural change, not an API change.
"""
import calendar
import re
import time

# --- pricing --------------------------------------------------------------------
# USD per MILLION tokens. Mirrors hooks/_config.py DEFAULTS["usage"]["pricing"] so
# this module is usable standalone (backfill, selftest) without a config file.
# The mirror is CHECKED, not asserted in prose: `pricing_divergences()` below and
# the `pp` selftest cases load the hooks' own table and name any field that drifts.
# They cannot be merged - hooks/ may import nothing from scripts/ - so the copy is
# deliberate and the case is what keeps it honest.
# Cache rates follow the published multipliers off base input: write 1.25x at the
# 5-minute TTL, 2x at the 1-hour TTL, read 0.1x.
#
# `_default` is Opus-tier on purpose: an unrecognized model is far more likely to be
# a new frontier release than a cheap one, and over-stating spend is the safer error
# for a cost display. Anything a project actually runs should get its own row.
DEFAULT_PRICING = {
    "_default":          {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-fable-5":    {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
    "claude-mythos-5":   {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
    "claude-opus-5":     {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-8":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-7":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-6":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-5":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-sonnet-5":   {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
    "claude-sonnet-4-6": {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
    "claude-sonnet-4-5": {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
    "claude-haiku-4-5":  {"in":  1.0, "out":  5.0, "cacheW5m":  1.25, "cacheW1h":  2.0, "cacheR": 0.1},
}

TOKEN_KEYS = ("in", "out", "cacheW5m", "cacheW1h", "cacheR")


def rates_for(model, pricing=None):
    """Resolve the price row for `model`: exact match, then LONGEST matching prefix
    (so a dated id like `claude-haiku-4-5-20251001` resolves to `claude-haiku-4-5`),
    then `_default`. Never raises."""
    table = pricing if isinstance(pricing, dict) and pricing else DEFAULT_PRICING
    fallback = table.get("_default") or DEFAULT_PRICING["_default"]
    if not isinstance(model, str) or not model:
        return fallback
    row = table.get(model)
    if isinstance(row, dict):
        return row
    best, best_len = None, -1
    for key, row in table.items():
        if key.startswith("_") or not isinstance(row, dict):
            continue
        if model.startswith(key) and len(key) > best_len:
            best, best_len = row, len(key)
    return best if best is not None else fallback


def price(counts, model, pricing=None):
    """USD for one bag of token counts. `counts` uses the TOKEN_KEYS names."""
    r = rates_for(model, pricing)
    total = 0.0
    for k in TOKEN_KEYS:
        try:
            total += float(counts.get(k) or 0) * float(r.get(k) or 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return total / 1_000_000.0


def pricing_divergences(mine, theirs, mine_name="mine", theirs_name="theirs"):
    """Every field-level disagreement between two pricing tables, sorted. `[]`
    means the two agree completely.

    Named rather than boolean because DEFAULT_PRICING above and
    `hooks/_config.py DEFAULTS["usage"]["pricing"]` are 13 models x 5 rates that
    must be kept identical BY HAND: hooks/ may import nothing from scripts/ and
    has to price a model with no config file present, so the table cannot be
    merged into one home. Each file carried a comment saying it mirrored the
    other and nothing read either comment. A checker that only says "the tables
    differ" hands the reader 65 numbers to diff, which is why every difference
    is named down to `model.rate: <value> vs <value>`.

    A table that is not a dict is REPORTED, never treated as empty-and-therefore-
    equal: the caller's most likely non-dict is a load that failed, and a failed
    load must not read as "they agree"."""
    if not isinstance(mine, dict):
        return ["%s is not a pricing table (%s)" % (mine_name, type(mine).__name__)]
    if not isinstance(theirs, dict):
        return ["%s is not a pricing table (%s)" % (theirs_name, type(theirs).__name__)]
    out = []
    for model in sorted(set(mine) | set(theirs)):
        if model not in mine:
            out.append("%s: absent from %s" % (model, mine_name))
            continue
        if model not in theirs:
            out.append("%s: absent from %s" % (model, theirs_name))
            continue
        row_a, row_b = mine[model], theirs[model]
        if not isinstance(row_a, dict) or not isinstance(row_b, dict):
            out.append("%s: rate row is not a dict (%s=%s, %s=%s)"
                       % (model, mine_name, type(row_a).__name__,
                          theirs_name, type(row_b).__name__))
            continue
        for rate in sorted(set(row_a) | set(row_b)):
            if rate not in row_a:
                out.append("%s.%s: absent from %s (%s has %r)"
                           % (model, rate, mine_name, theirs_name, row_b[rate]))
            elif rate not in row_b:
                out.append("%s.%s: absent from %s (%s has %r)"
                           % (model, rate, theirs_name, mine_name, row_a[rate]))
            elif row_a[rate] != row_b[rate]:
                out.append("%s.%s: %s %r vs %s %r"
                           % (model, rate, mine_name, row_a[rate],
                              theirs_name, row_b[rate]))
    return out


# --- timestamps -----------------------------------------------------------------
# Hand-rolled so the parse is identical on Python 3.8+ (datetime.fromisoformat only
# learned to accept a trailing `Z` in 3.11, and is picky about fractional digits).
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_ts(value):
    """ISO-8601 -> epoch seconds (float, UTC). None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    try:
        epoch = float(calendar.timegm(
            (int(y), int(mo), int(d), int(hh), int(mm), int(ss), 0, 0, 0)))
    except (ValueError, OverflowError):
        return None
    if frac:
        epoch += float("0." + frac)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        try:
            epoch -= sign * (int(body[:2]) * 3600 + int(body[2:4]) * 60)
        except ValueError:
            return None
    return epoch


def hour_bucket(value):
    """ISO-8601 -> `YYYY-MM-DDTHH` in UTC. None when unparseable.

    Rows are keyed by this, which is what gives the report an exact day x hour
    heatmap and keeps a full backfill shaped like incremental metering."""
    epoch = parse_ts(value)
    if epoch is None:
        return None
    g = time.gmtime(epoch)
    return "%04d-%02d-%02dT%02d" % (g.tm_year, g.tm_mon, g.tm_mday, g.tm_hour)


def bucket_month(bucket):
    """`YYYY-MM-DDTHH` -> `YYYY-MM` (the ledger file it belongs in)."""
    return bucket[:7] if isinstance(bucket, str) and len(bucket) >= 7 else "unknown"


def bucket_date(bucket):
    return bucket[:10] if isinstance(bucket, str) and len(bucket) >= 10 else ""


def bucket_hour(bucket):
    """`YYYY-MM-DDTHH` -> int hour, or None."""
    try:
        return int(bucket[11:13])
    except (TypeError, ValueError, IndexError):
        return None


# --- aggregation ----------------------------------------------------------------
_SET_FIELDS = ("sessions", "authors", "models", "tasks", "phases")


def _blank():
    slot = {k: 0 for k in TOKEN_KEYS}
    slot["msgs"] = 0
    slot["costUSD"] = 0.0
    for f in _SET_FIELDS:
        slot["_" + f] = set()
    return slot


def _add(slot, row):
    for k in TOKEN_KEYS:
        try:
            slot[k] += int(row.get(k) or 0)
        except (TypeError, ValueError):
            pass
    try:
        slot["msgs"] += int(row.get("msgs") or 0)
    except (TypeError, ValueError):
        pass
    try:
        slot["costUSD"] += float(row.get("costUSD") or 0.0)
    except (TypeError, ValueError):
        pass
    for field, key in (("sessions", "sessionId"), ("authors", "author"),
                       ("models", "model"), ("tasks", "taskId"),
                       ("phases", "phaseId")):
        value = row.get(key)
        if value:
            slot["_" + field].add(value)


def _finish(slot):
    out = {k: slot[k] for k in TOKEN_KEYS}
    out["msgs"] = slot["msgs"]
    out["costUSD"] = round(slot["costUSD"], 6)
    out["tokens"] = sum(slot[k] for k in TOKEN_KEYS)
    for f in _SET_FIELDS:
        out[f] = len(slot["_" + f])
    cached = out["cacheR"]
    billed = out["in"] + out["cacheW5m"] + out["cacheW1h"] + cached
    out["cacheHitPct"] = round(100.0 * cached / billed, 1) if billed else 0.0
    return out


GROUP_KEYS = {
    "phase": lambda r: r.get("phaseId") or "--",
    "task": lambda r: r.get("taskId") or "--",
    "model": lambda r: r.get("model") or "unknown",
    "author": lambda r: r.get("author") or "unknown",
    "agent": lambda r: r.get("agentType") or "orchestrator",
    "day": lambda r: bucket_date(r.get("ts")) or "unknown",
    "month": lambda r: bucket_month(r.get("ts")),
    "hour": lambda r: r.get("ts") or "unknown",
    "session": lambda r: r.get("sessionId") or "unknown",
    "branch": lambda r: r.get("branch") or "--",
    "attr": lambda r: r.get("attr") or "unattributed",
}


def totals(rows):
    slot = _blank()
    for row in rows:
        _add(slot, row)
    return _finish(slot)


def aggregate(rows, by):
    """Group rows by one of GROUP_KEYS -> {key: finished totals}. Unknown `by`
    raises KeyError, which the CLI turns into a usage error."""
    # The accumulator is fetched, not `setdefault`-ed, ON PURPOSE. `setdefault`
    # evaluates `_blank()` EAGERLY, so a dict plus five `set()` objects were
    # built and thrown away for every row whose key already existed: 20,000
    # `_blank()` calls to fill 50 day buckets, and `aggregate` runs 11 times per
    # report and per panel usage request. Calling `keyfn` once instead of twice
    # is the rest of it. Measured 30.0 ms -> 18.4 ms over 20,000 rows.
    # `_blank()` never returns None, so a `None` from `.get` means "absent".
    keyfn = GROUP_KEYS[by]
    acc = {}
    for row in rows:
        key = keyfn(row)
        slot = acc.get(key)
        if slot is None:
            slot = _blank()
            acc[key] = slot
        _add(slot, row)
    return {k: _finish(v) for k, v in acc.items()}


# Where spend with no area lands. NOT a GROUP_KEYS entry: every GROUP_KEYS
# dimension reads a field the row itself carries, while area is a property of
# the PLAN joined in at read time — so re-tagging a phase re-attributes its
# whole ledger history on the next read, with no backfill and no row rewriting.
UNTAGGED_AREA = "untagged"


def _row_area_tags(row, tags_by_phase):
    """The area tags one row counts under — [UNTAGGED_AREA] when its phase has
    none, is unknown to the plan, or the row never carried a phase at all."""
    tags = (tags_by_phase or {}).get(row.get("phaseId") or "")
    return tags if tags else [UNTAGGED_AREA]


def aggregate_area(rows, tags_by_phase):
    """Ledger spend by area tag -> {tag: finished totals}.

    `tags_by_phase` is {phaseId: [tags]}, built by `_areas.phase_tags` and passed
    in ready-made — this module stays stdlib-only and does not import _areas.

    A multi-tag phase counts its rows under EACH of its tags, so per-tag figures
    can sum PAST the ledger total; every renderer that shows per-area numbers
    must say so. Rows that resolve to no tag land in `untagged`."""
    # Lazy accumulator for the same reason `aggregate` uses one - see the comment
    # there. This one allocated once per (row x tag), which is WORSE: a two-tag
    # phase paid for two discarded `_blank()`s per row.
    acc = {}
    for row in rows:
        for tag in _row_area_tags(row, tags_by_phase):
            slot = acc.get(tag)
            if slot is None:
                slot = _blank()
                acc[tag] = slot
            _add(slot, row)
    return {k: _finish(v) for k, v in acc.items()}


def rows_for_area(rows, tags_by_phase, tag):
    """The subset of rows aggregate_area counts under `tag` — the ONE statement
    of the join, shared with the CLI's --area filter so a filtered dashboard and
    the BY AREA table can never disagree. `untagged` selects the untagged bucket."""
    want = (tag or "").strip()
    return [r for r in rows if want in _row_area_tags(r, tags_by_phase)]


def heatmap(rows):
    """7x24 day-of-week x hour token grid. grid[0] is Monday, matching
    `time.gmtime().tm_wday`."""
    grid = [[0] * 24 for _ in range(7)]
    for row in rows:
        bucket = row.get("ts")
        epoch = parse_ts((bucket or "") + ":00:00Z")
        hour = bucket_hour(bucket)
        if epoch is None or hour is None:
            continue
        wday = time.gmtime(epoch).tm_wday
        grid[wday][hour] += sum(int(row.get(k) or 0) for k in TOKEN_KEYS)
    return grid


# --- selftest -------------------------------------------------------------------
def _selftest():
    import os

    cases = []

    def check(label, cond, detail=""):
        cases.append((label, bool(cond), detail))

    # --- pricing -----------------------------------------------------------
    check("price: exact model match",
          rates_for("claude-sonnet-5")["in"] == 3.0)
    check("price: longest-prefix match resolves a dated id",
          rates_for("claude-haiku-4-5-20251001")["out"] == 5.0)
    check("price: Fable/Mythos priced above Opus tier, not silently defaulted",
          rates_for("claude-fable-5")["out"] == 50.0
          and rates_for("claude-mythos-5")["out"] == 50.0)
    check("price: a Sonnet 4.x id does not fall through to the Opus default",
          rates_for("claude-sonnet-4-5")["out"] == 15.0)
    check("price: unknown model falls back to _default",
          rates_for("some-future-model")["in"] == DEFAULT_PRICING["_default"]["in"])
    check("price: non-string model falls back",
          rates_for(None)["in"] == DEFAULT_PRICING["_default"]["in"])
    one_m = {"in": 1_000_000, "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0}
    check("price: 1M input on opus-5 == $5.00",
          abs(price(one_m, "claude-opus-5") - 5.0) < 1e-9)
    both = {"in": 0, "out": 0, "cacheW5m": 1_000_000, "cacheW1h": 1_000_000,
            "cacheR": 0}
    check("price: both cache-write tiers priced apart (6.25 + 10.00)",
          abs(price(both, "claude-opus-5") - 16.25) < 1e-9)
    check("price: cache read is 0.1x base input",
          abs(price({"in": 0, "out": 0, "cacheW5m": 0, "cacheW1h": 0,
                     "cacheR": 1_000_000}, "claude-opus-5") - 0.5) < 1e-9)

    # --- pp: the 65 numbers that used to be kept true by two comments -------
    # DEFAULT_PRICING and hooks/_config.py DEFAULTS["usage"]["pricing"] are the
    # same 13 models x 5 rates, and each file's comment said it mirrored the
    # other. Nothing read either comment. They cannot be merged (hooks/ may
    # import nothing from scripts/, and the hook must price a model standalone),
    # so the agreement is pinned here instead - the scripts/ side is the one that
    # is allowed to look at both.
    def _deep_pricing_copy(table):
        return dict((model, dict(row)) for model, row in table.items())

    def _load_hooks_pricing():
        """`(table, error)` for hooks/_config.py's own pricing map, loaded BY PATH.

        NOT through `_loader.load_hooks_config()`, which is how `_help.py` and
        `validate-config.py` reach the same file: `_loader` is this module's PEER
        in `_deps.LAYERS` (both layer 1), so an `import _loader` here is a
        sideways edge, and `_deps.layer_violations()` names it - measured, it adds
        a 21st entry to a KNOWN_LAYER_DEBT list whose case asserts EXACT equality.
        The four lines below are what `_loader.load()` does, minus the shared
        cache this one call has no use for.

        The failure is RETURNED, never swallowed: a hooks config that would not
        load must land as a failing case of its own, not as an empty divergence
        list that reads exactly like agreement."""
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "hooks", "_config.py")
        try:
            spec = importlib.util.spec_from_file_location(
                "audit_hooks_config_ledger_selftest", path)
            if spec is None or spec.loader is None:
                return None, "no import spec for %s" % path
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.DEFAULTS["usage"]["pricing"], None
        except Exception as exc:     # any failure is reported, not absorbed
            return None, "%s: %s" % (type(exc).__name__, exc)

    # The second-direction case: a divergence checker that ALWAYS reports
    # something would fail every `pp` case below except this one, and this one
    # is the only case that goes red when it does.
    check("pp1 two identical tables diverge in nothing",
          pricing_divergences(DEFAULT_PRICING,
                              _deep_pricing_copy(DEFAULT_PRICING)) == [])
    _pp_drift = _deep_pricing_copy(DEFAULT_PRICING)
    _pp_drift["claude-sonnet-5"]["cacheW1h"] = 6.5
    _pp_named = pricing_divergences(DEFAULT_PRICING, _pp_drift,
                                    "ledger", "hooks")
    check("pp2 one drifted rate is named down to model.rate WITH both values, "
          "and is the ONLY thing reported - a checker that just says 'the "
          "tables differ' sends someone diffing 65 numbers by hand",
          _pp_named == ["claude-sonnet-5.cacheW1h: ledger 6.0 vs hooks 6.5"],
          repr(_pp_named))
    _pp_gone = _deep_pricing_copy(DEFAULT_PRICING)
    del _pp_gone["claude-haiku-4-5"]
    check("pp3 a model present on one side only is named by model",
          pricing_divergences(DEFAULT_PRICING, _pp_gone, "ledger", "hooks")
          == ["claude-haiku-4-5: absent from hooks"])
    _pp_extra = _deep_pricing_copy(DEFAULT_PRICING)
    _pp_extra["claude-future-9"] = dict(DEFAULT_PRICING["_default"])
    check("pp4 ...and so is a model only the OTHER side has, so the check reads "
          "both directions",
          pricing_divergences(DEFAULT_PRICING, _pp_extra, "ledger", "hooks")
          == ["claude-future-9: absent from ledger"])
    _pp_partial = _deep_pricing_copy(DEFAULT_PRICING)
    del _pp_partial["claude-opus-5"]["cacheR"]
    check("pp5 a missing RATE inside a row is named too, not just a missing row",
          pricing_divergences(DEFAULT_PRICING, _pp_partial, "ledger", "hooks")
          == ["claude-opus-5.cacheR: absent from hooks (ledger has 0.5)"])
    check("pp6 a table that is not a dict - the shape a failed load has - is "
          "REPORTED, never treated as empty-and-therefore-equal",
          pricing_divergences(DEFAULT_PRICING, None, "ledger", "hooks")
          == ["hooks is not a pricing table (NoneType)"]
          and pricing_divergences(None, DEFAULT_PRICING, "ledger", "hooks")
          == ["ledger is not a pricing table (NoneType)"])

    _hooks_pricing, _hooks_err = _load_hooks_pricing()
    check("pp7 hooks/_config.py loaded and carries DEFAULTS['usage']['pricing'] "
          "at all - its own case, so a load failure can never be mistaken for "
          "the tables agreeing",
          _hooks_err is None and isinstance(_hooks_pricing, dict)
          and len(_hooks_pricing) == len(DEFAULT_PRICING),
          _hooks_err or ("got %r" % (type(_hooks_pricing).__name__,)))
    _hooks_diff = pricing_divergences(DEFAULT_PRICING, _hooks_pricing,
                                      "usage_ledger.DEFAULT_PRICING",
                                      "hooks/_config.py")
    check("pp8 usage_ledger.DEFAULT_PRICING and hooks/_config.py "
          "DEFAULTS['usage']['pricing'] are identical, model for model and rate "
          "for rate - the duplication is deliberate, the agreement is now read",
          _hooks_diff == [], " | ".join(_hooks_diff))

    # --- timestamps --------------------------------------------------------
    check("ts: millisecond Z form parses",
          parse_ts("2026-08-06T07:20:10.266Z") is not None)
    check("ts: microsecond form parses",
          parse_ts("2026-08-06T07:20:10.266123Z") is not None)
    check("ts: offset form normalizes to UTC",
          parse_ts("2026-08-06T09:20:10+02:00") == parse_ts("2026-08-06T07:20:10Z"))
    check("ts: garbage -> None", parse_ts("not-a-date") is None)
    check("ts: hour bucket is UTC-normalized",
          hour_bucket("2026-08-06T09:20:10+02:00") == "2026-08-06T07")
    check("ts: bucket_month / bucket_date / bucket_hour",
          bucket_month("2026-08-06T07") == "2026-08"
          and bucket_date("2026-08-06T07") == "2026-08-06"
          and bucket_hour("2026-08-06T07") == 7)

    # --- aggregation -------------------------------------------------------
    # The row fixture below is the one the `ag` cases already carried; the `agg`
    # and `mo` cases read it too, because the scan output they used to run over
    # is produced by usage_ledger.py, one layer above this file.
    def _ag_row(ts, phase, tokens):
        return {"ts": ts, "phaseId": phase, "taskId": phase + ".1",
                "model": "claude-opus-5", "author": "a@x",
                "sessionId": "s-" + phase, "branch": "main", "attr": "task",
                "agentType": "audit-executor", "msgs": 1, "in": tokens,
                "out": 2 * tokens, "cacheW5m": 1, "cacheW1h": 2,
                "cacheR": 3, "costUSD": 0.125 * tokens}

    # Three day keys out of five rows: two buckets repeat (only a repeated
    # key can tell the eager and lazy versions apart) and one occurs once.
    # Every `ts` is distinct, so grouping by "hour" gives five keys for the
    # same rows - that is what makes ag5 below a real second direction.
    _ag_rows = [_ag_row("2026-08-01T09", "P1", 10),
                _ag_row("2026-08-01T10", "P1", 20),
                _ag_row("2026-08-01T11", "P2", 40),
                _ag_row("2026-08-02T09", "P2", 80),
                _ag_row("2026-08-03T09", "P3", 160)]

    agg_all = totals(_ag_rows)
    check("agg: tokens is the sum of every token key",
          agg_all["tokens"] == sum(agg_all[k] for k in TOKEN_KEYS))
    check("agg: cache hit pct in range",
          0.0 <= agg_all["cacheHitPct"] <= 100.0)
    check("agg: unknown group key raises",
          _raises(lambda: aggregate(_ag_rows, "nope")))
    by_attr = aggregate(_ag_rows, "attr")
    check("agg: every row carries an attribution bucket",
          sum(v["msgs"] for v in by_attr.values()) == agg_all["msgs"])
    grid = heatmap(_ag_rows)
    check("agg: heatmap is 7x24", len(grid) == 7 and len(grid[0]) == 24)
    check("agg: heatmap totals match", sum(sum(r) for r in grid) == agg_all["tokens"])
    # --- month bucket (mo) --------------------------------------------
    check("mo1 'month' is a first-class group key, so --by month and byMonth "
          "exist without their own code paths",
          "month" in GROUP_KEYS)
    by_month = aggregate(_ag_rows, "month")
    check("mo2 every row lands in its calendar month",
          by_month.get("2026-08", {}).get("msgs") == agg_all["msgs"])
    _mo_rows = [dict(_ag_rows[0], ts="2026-07-31T23"),
                dict(_ag_rows[0], ts="2026-08-01T00")]
    _mo = aggregate(_mo_rows, "month")
    check("mo3 a month boundary splits two adjacent hours into two months",
          set(_mo) == {"2026-07", "2026-08"}
          and _mo["2026-07"]["msgs"] == _mo["2026-08"]["msgs"])
    check("mo4 a garbled ts groups under 'unknown', never dropped",
          aggregate([dict(_ag_rows[0], ts=None)], "month")
          .get("unknown", {}).get("msgs") == _ag_rows[0]["msgs"])

    # --- aggregate_area (aa): the read-time area join ------------------
    # tags_by_phase arrives ready-made (_areas.phase_tags) - this module
    # must stay stdlib-only, so the join is data in, never an import.
    _aa_rows = [
        {"ts": "2026-08-01T10", "phaseId": "P1", "msgs": 1, "in": 10,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 1.0},
        {"ts": "2026-08-02T10", "phaseId": "P2", "msgs": 1, "in": 20,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 2.0},
        {"ts": "2026-08-03T10", "phaseId": "P3", "msgs": 1, "in": 40,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 4.0},
        {"ts": "2026-08-04T10", "phaseId": "P9", "msgs": 1, "in": 80,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 8.0},
        {"ts": "2026-08-05T10", "msgs": 1, "in": 160, "out": 0,
         "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 16.0},
    ]
    _aa_map = {"P1": ["backend"], "P2": ["backend", "web"], "P3": []}
    _aa = aggregate_area(_aa_rows, _aa_map)
    check("aa1 rows join to areas through their phase's tags",
          _aa.get("backend", {}).get("msgs") == 2
          and _aa.get("backend", {}).get("in") == 30
          and _aa.get("web", {}).get("in") == 20)
    check("aa2 a multi-tag phase counts under EACH tag, so per-tag figures "
          "can sum past the ledger total - renderers must say so",
          sum(v["msgs"] for v in _aa.values()) == 6
          and totals(_aa_rows)["msgs"] == 5)
    check("aa3 no-tag phase, unknown phase and phase-less row all land in "
          "'untagged', never dropped",
          _aa.get(UNTAGGED_AREA, {}).get("msgs") == 3
          and _aa.get(UNTAGGED_AREA, {}).get("in") == 280)
    check("aa4 the join is read-time: a re-tagged map re-attributes the SAME "
          "rows with no backfill",
          aggregate_area(_aa_rows, {"P1": ["mobile"]})
          .get("mobile", {}).get("in") == 10)
    check("aa5 empty rows are {}, and a None map buckets everything untagged "
          "rather than raising",
          aggregate_area([], _aa_map) == {}
          and aggregate_area(_aa_rows, None)
          .get(UNTAGGED_AREA, {}).get("msgs") == 5)
    check("aa6 rows_for_area selects exactly the rows aggregate_area counts "
          "under the tag - one join, two callers, no drift",
          totals(rows_for_area(_aa_rows, _aa_map, "backend"))["in"] == 30
          == _aa.get("backend", {}).get("in")
          and totals(rows_for_area(_aa_rows, _aa_map, "web"))["in"] == 20
          == _aa.get("web", {}).get("in"))
    check("aa7 ...including the untagged bucket, and an unknown tag is []",
          totals(rows_for_area(_aa_rows, _aa_map, "untagged"))["in"] == 280
          and rows_for_area(_aa_rows, _aa_map, "nope") == [])

    # --- ag: the lazy accumulator (a measured hot spot) -----------------
    # `acc.setdefault(k, _blank())` evaluates `_blank()` EAGERLY, so a dict
    # plus five `set()`s were built and discarded for every row whose key
    # already existed - 20,000 allocations to fill 50 day buckets, and
    # `aggregate` runs 11 times per report and per panel usage request.
    # THE TWO HALVES ARE PROVEN APART ON PURPOSE: an output assertion cannot
    # see an allocation (the eager version returns exactly the same dict),
    # and an allocation count cannot see a wrong number.
    def _aggregate_eager(rows, by):
        """The pre-fix body, kept as an ORACLE so "faster" can never quietly
        become "different"."""
        keyfn = GROUP_KEYS[by]
        acc = {}
        for row in rows:
            acc.setdefault(keyfn(row), _blank())
            _add(acc[keyfn(row)], row)
        return dict((k, _finish(v)) for k, v in acc.items())

    def _aggregate_area_eager(rows, tags_by_phase):
        acc = {}
        for row in rows:
            for tag in _row_area_tags(row, tags_by_phase):
                acc.setdefault(tag, _blank())
                _add(acc[tag], row)
        return dict((k, _finish(v)) for k, v in acc.items())
    check("ag1 the fixture really does repeat keys - over rows that are all "
          "unique the two versions are indistinguishable and ag4 would pass "
          "on the bug",
          len(aggregate(_ag_rows, "day")) == 3 and len(_ag_rows) == 5)
    check("ag2 output is unchanged against the eager setdefault oracle, for "
          "every group key, over repeated keys / a single-occurrence key / "
          "an empty ledger",
          all(aggregate(_r, _by) == _aggregate_eager(_r, _by)
              for _r in (_ag_rows, _ag_rows[4:], [])
              for _by in sorted(GROUP_KEYS)))
    _ag_tags = {"P1": ["backend"], "P2": ["backend", "web"], "P3": []}
    check("ag3 ...and aggregate_area's output is unchanged too, including "
          "the multi-tag phase that allocated TWICE per row",
          all(aggregate_area(_r, _ag_tags) == _aggregate_area_eager(_r, _ag_tags)
              for _r in (_ag_rows, _ag_rows[4:], [])))

    # `_blank` is swapped for a counting stub and restored in `finally` -
    # the same technique audit-journal.py's selftest uses for its anchor
    # counter. THE COUNT IS THE DEFECT; nothing else in the suite can see it.
    _ag_calls = [0]
    _ag_real_blank = _blank

    def _ag_counting_blank():
        _ag_calls[0] += 1
        return _ag_real_blank()

    globals()["_blank"] = _ag_counting_blank
    try:
        _ag_calls[0] = 0
        aggregate(_ag_rows, "day")
        _ag_by_day = _ag_calls[0]
        _ag_calls[0] = 0
        aggregate(_ag_rows, "hour")
        _ag_by_hour = _ag_calls[0]
        _ag_calls[0] = 0
        aggregate([], "day")
        _ag_empty = _ag_calls[0]
        _ag_calls[0] = 0
        aggregate_area(_ag_rows, _ag_tags)
        _ag_area = _ag_calls[0]
        _ag_calls[0] = 0
        _aggregate_eager(_ag_rows, "day")
        _ag_eager_day = _ag_calls[0]
    finally:
        globals()["_blank"] = _ag_real_blank

    check("ag4 `_blank()` is called once per KEY, not once per row: 3 "
          "allocations for 5 rows over 3 day buckets",
          _ag_by_day == 3, "got %d" % _ag_by_day)
    # The other direction. A "lazy" accumulator that reused ONE slot, or
    # allocated nothing, would satisfy ag4 by accident; it cannot satisfy
    # this, because here every row genuinely IS its own key.
    check("ag5 ...and once per row when every row is its own key, so ag4 is "
          "not passing on a version that stopped allocating at all",
          _ag_by_hour == 5, "got %d" % _ag_by_hour)
    check("ag6 an empty ledger allocates nothing", _ag_empty == 0,
          "got %d" % _ag_empty)
    check("ag7 aggregate_area allocates once per TAG (backend, web, "
          "untagged), not once per row x tag - 3, not 6",
          _ag_area == 3, "got %d" % _ag_area)
    # The counter itself is proven to fire: run the ORACLE through it and
    # watch the pre-fix number come back. Without this, ag4/ag7 could be
    # green because the stub was never installed.
    check("ag8 the counter is real - the eager oracle, measured the same "
          "way, still allocates once per ROW (5), which is the defect",
          _ag_eager_day == 5, "got %d" % _ag_eager_day)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if (detail and not ok) else ""))
    print("\n_usage_core: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _usage_core.py --selftest\n")
    raise SystemExit(2)
