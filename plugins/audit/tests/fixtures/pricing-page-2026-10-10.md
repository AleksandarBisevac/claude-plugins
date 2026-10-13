# Pricing page excerpt, as of 2026-10-10

Checked-in excerpt of the rows `PRICING_SOURCE_URL`
(https://platform.claude.com/docs/en/about-claude/pricing) carried on this date, for the
two rows `test__usage_core.py` pins against. Transcribed by hand — this file is the
basis a reader checks a shipped rate against, not something any script derives.

USD per MILLION tokens.

## Claude Sonnet 5.5

| Input | 5m cache write | 1h cache write | Cache read | Output |
|---|---|---|---|---|
| $2 | $2.50 | $4 | $0.10 | $10 |

## Claude Haiku 5.5

Two prompt-length tiers, the published long-prompt split:

**Prompts up to 100,000 tokens**

| Input | 5m cache write | 1h cache write | Cache read | Output |
|---|---|---|---|---|
| $0.10 | $0.125 | $0.20 | $0.01 | $0.50 |

**Prompts over 100,000 tokens**

| Input | 5m cache write | 1h cache write | Cache read | Output |
|---|---|---|---|---|
| $0.50 | $0.625 | $1 | $0.05 | $2.50 |

The shipped table carries Haiku 5.5's base (up to 100,000 prompt tokens) tier only —
`rates_for()` has no notion of a prompt-length-conditioned rate, only a model id and an
effective date, so the long-prompt tier has no row until that split is built. Recorded
here so correcting that is a quoted number away, not a re-read of the page.
