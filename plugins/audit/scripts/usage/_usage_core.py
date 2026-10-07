#!/usr/bin/env python3
"""
Prices, timestamps and roll-ups — the arithmetic every other usage module stands on.

Split out of `usage_ledger.py` because the two halves above it (the transcript
scanner in `usage_ledger.py`, the presentation analytics that were then one file)
both need this and neither needs the other. Nothing here reads a file, spawns a
process or knows what a transcript is: every function takes values and returns
values, which is why its cases need no fixture directory at all.

Four things live here, and the reason each is HERE rather than beside its caller:

  pricing      - a rate table and the cost of a bag of tokens. `hooks/_config.py`
                 keeps its own copy (hooks may import nothing from scripts/) and
                 `pricing_divergences()` is what keeps the two honest.
  timestamps   - one ISO parse and one hour-bucket rule. Two parsers would be two
                 answers to 'which hour did this land in', and the ledger's whole
                 shape is that bucket.
  aggregation  - `totals` / `aggregate` / `aggregate_area` / `heatmap`, the
                 roll-ups the CLI, the report and the panel all read. One home, so
                 three surfaces cannot disagree about a number. `priced_at_read`
                 prices the rows they sum at the resolved table first.
  rows + plan  - `task_index`, `_tokens`, `_cost`: one row's tokens, one row's
                 cost, and the plan's tasks by id. They arrived with the U3.2
                 split and the LAYER is why they are here rather than in a base
                 module of their own - the four analytics passes that read them
                 all sit at layer 2, and a layer-2 module may not import a peer.
                 See the section at the foot of this file.

`usage_ledger.py` re-exports every public name defined here, so no call site names
this module: the split is a structural change, not an API change.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__usage_core.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import calendar
import os
import re
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

# --- pricing --------------------------------------------------------------------
# USD per MILLION tokens. Mirrors hooks/_config.py DEFAULTS["usage"]["pricing"] so
# this module is usable standalone (backfill, selftest) without a config file.
# The mirror is CHECKED, not asserted in prose: `pricing_divergences()` below and
# `tests/test__usage_core.py`'s `pp` cases load the hooks' own table and name any
# field that drifts.
# They cannot be merged - hooks/ may import nothing from scripts/ - so the copy is
# deliberate and the case is what keeps it honest. The date and the page the rates
# were read from are mirrored the same way and held equal by
# `pricing_provenance_divergences()`.
# Every rate is copied from the page, not derived: the cache writes follow the
# published 1.25x (5-minute TTL) and 2x (1-hour TTL) multipliers off base input,
# but the read multiplier is not uniform - the page prices some models' cache read
# below the usual 0.1x, so a row computed from base input would overcharge them.
#
# Resolution is by LONGEST PREFIX, so a point release needs its own row whenever
# its rates differ from its family's: without one, `claude-opus-5-5` resolves to
# `claude-opus-5` and is priced at another model's rate with no warning.
#
# `_default` is Opus-tier on purpose: an unrecognized model is far more likely to be
# a new frontier release than a cheap one, and over-stating spend is the safer error
# for a cost display. Anything a project actually runs should get its own row.
PRICING_AS_OF = "2026-10-06"
PRICING_SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
DEFAULT_PRICING = {
    "_default":          {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-fable-5":    {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
    "claude-fable-5-1":  {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 0.25},
    "claude-mythos-5":   {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
    "claude-mythos-5-1": {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 0.25},
    "claude-opus-5":     {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-5-5":   {"in":  4.0, "out": 20.0, "cacheW5m":  5.00, "cacheW1h":  8.0, "cacheR": 0.2},
    "claude-opus-4-8":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-7":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-6":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-5":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-sonnet-5":   {"in":  2.0, "out": 10.0, "cacheW5m":  2.50, "cacheW1h":  4.0, "cacheR": 0.2},
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
    `hooks/_config.py DEFAULTS["usage"]["pricing"]` must be kept identical BY
    HAND: hooks/ may import nothing from scripts/ and has to price a model with
    no config file present, so the table cannot be merged into one home. Each
    file carried a comment saying it mirrored the other and nothing read either
    comment. A checker that only says "the tables differ" hands the reader every
    rate of both tables to diff, which is why every difference is named down to
    `model.rate: <value> vs <value>`.

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


_PROVENANCE_KEYS = ("pricingAsOf", "source")


def _blank_field(value):
    return not isinstance(value, str) or not value.strip()


def pricing_provenance_divergences(mine, theirs, mine_name="mine",
                                   theirs_name="theirs"):
    """Every disagreement between two `{pricingAsOf, source}` provenances,
    worded the way `pricing_divergences()` words a rate. `[]` means both name
    the same date and the same page.

    The date and the URL are mirrored for the same reason the rates are, and
    drift the same way: a table corrected in both files with its date bumped in
    one prints a basis the other copy's numbers did not come from.

    A blank or missing field is reported on its own side even when the other
    side is blank too - two empty dates agree, and say nothing. A provenance
    that is not a dict is reported, never read as agreement."""
    if not isinstance(mine, dict):
        return ["%s is not a pricing provenance (%s)" % (mine_name, type(mine).__name__)]
    if not isinstance(theirs, dict):
        return ["%s is not a pricing provenance (%s)"
                % (theirs_name, type(theirs).__name__)]
    out = []
    for key in _PROVENANCE_KEYS:
        a, b = mine.get(key), theirs.get(key)
        blanks = [name for name, value in ((mine_name, a), (theirs_name, b))
                  if _blank_field(value)]
        if blanks:
            out.extend("%s: blank in %s" % (key, name) for name in blanks)
        elif a != b:
            out.append("%s: %s %r vs %s %r" % (key, mine_name, a, theirs_name, b))
    return out


# Which of the three places a project's table can come from priced it. Data, not
# a sentence: a surface that names its basis words it from these.
PRICING_BASES = ("manifest", "config", "shipped")


def _declared_table(block):
    """`block["pricing"]` when it is a non-empty dict, else None. An empty table
    declares nothing: it would price every model at the zero row a lookup with
    nothing in it falls back past."""
    if not isinstance(block, dict):
        return None
    table = block.get("pricing")
    return table if isinstance(table, dict) and table else None


def _declared_as_of(block):
    """`block["pricingAsOf"]` trimmed, or None - a whitespace-only date is no
    date, the same normalisation every reader of this key applies."""
    value = block.get("pricingAsOf") if isinstance(block, dict) else None
    return (value.strip() or None) if isinstance(value, str) else None


def _copy_table(table):
    return dict((k, dict(v) if isinstance(v, dict) else v)
                for k, v in table.items())


def resolve_pricing(manifest, config):
    """The one price table a project is priced at, and which place it came from.

    -> {"table":  the rate table, a copy the caller may keep,
        "basis":  one of PRICING_BASES,
        "asOf":   the date the declaring place gives its rates, or None,
        "source": the page the rates were read from, or None}

    Precedence, first match wins:
      * `manifest` - the plan's `meta.usage.pricing`;
      * `config`   - `usage.pricing` of the RAW `.claude/audit.config.json`
        (as parsed, not merged with defaults);
      * `shipped`  - DEFAULT_PRICING, dated PRICING_AS_OF from
        PRICING_SOURCE_URL.

    A declared table, from either place, is laid over the shipped table
    model by model: a named row replaces the shipped row whole, every other
    row stays shipped. That is `hooks/_config.usage_cfg`'s merge for the
    config, and the plan's table gets the same one so a model it does not
    name is priced at its shipped row, never at a `_default` the plan may
    not declare.

    `asOf` is the declaring place's own `pricingAsOf`, None when it gives
    none - an overlay's unnamed rows are still the shipped ones, but the
    date names what the project declared. Only the shipped table carries a
    source; a project's own table answers to whatever page it was copied from,
    which neither file names.

    The config must be the raw file: a config already merged with defaults
    always carries a table, and the basis would read `config` for a project
    that declared nothing. Never raises."""
    meta = (manifest or {}).get("meta") if isinstance(manifest, dict) else None
    meta_usage = meta.get("usage") if isinstance(meta, dict) else None
    declared = _declared_table(meta_usage)
    table = _copy_table(DEFAULT_PRICING)
    if declared is not None:
        table.update(_copy_table(declared))
        return {"table": table, "basis": "manifest",
                "asOf": _declared_as_of(meta_usage), "source": None}
    cfg_usage = config.get("usage") if isinstance(config, dict) else None
    overlay = _declared_table(cfg_usage)
    if overlay is not None:
        table.update(_copy_table(overlay))
        return {"table": table, "basis": "config",
                "asOf": _declared_as_of(cfg_usage), "source": None}
    return {"table": table, "basis": "shipped", "asOf": PRICING_AS_OF,
            "source": PRICING_SOURCE_URL}


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


def _priceable(row):
    """True when every TOKEN_KEYS field is a number, so the row can be priced
    again whole. A row missing one cannot: pricing the absent field at zero
    would print a figure lower than anything the row ever cost."""
    return all(isinstance(row.get(k), (int, float))
               and not isinstance(row.get(k), bool) for k in TOKEN_KEYS)


def priced_at_read(rows, table):
    """Every row's `costUSD` as `table` prices its token counts now.

    -> {"rows": copies of `rows`, each priceable row's `costUSD` replaced,
        "pricedWhenWritten": how many rows kept their stored figure}

    The surfaces print a cost beside a phrase naming the resolved table, while
    a row's stored `costUSD` was priced when it was written, at a rate the
    ledger never recorded. So each surface sums these copies rather than the
    rows it read, and every roll-up below inherits the resolved table. The
    rows handed in are not touched: the ledger stays as written. Each figure
    is rounded the way the writer rounds one, so a ledger written at the
    resolved table sums to exactly what it stored.

    A row that cannot be priced again (`_priceable`) keeps its stored figure,
    and the count of those is returned for the rate phrase to state - never
    left as a silent mix of two tables."""
    out, kept = [], 0
    for row in rows:
        copy = dict(row)
        if _priceable(row):
            copy["costUSD"] = round(price(row, row.get("model"), table), 6)
        else:
            kept += 1
        out.append(copy)
    return {"rows": out, "pricedWhenWritten": kept}


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


# --- rows and plan --------------------------------------------------------------
# The three readers every analytics pass starts from: one row's tokens, one row's
# cost, and the plan's tasks by id. They arrived here with the U3.2 split of
# `_usage_analytics.py`, and the layer is the reason. The four passes that file
# was cut into all sit at layer 2 so that `usage_ledger` (layer 3) can import
# them, and a module at layer 2 may not import a peer - so anything more than one
# of them needs has to live at layer 1 or below, which is where this module
# already was. `_tokens` also needs `TOKEN_KEYS`, defined above, so a new layer-1
# module could not have held it without importing this one, which is the same
# peer edge one layer down.
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


if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_usage_core.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__usage_core.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: _usage_core.py --selftest\n")
    raise SystemExit(2)
