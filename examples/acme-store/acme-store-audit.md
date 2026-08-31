# ACME Store — security & correctness audit

repo: acme-store · generated 2026-08-31 17:01 UTC

> Phase 0 (framework upgrade) was finished before this project started recording test runs, so nothing in it points at one — the test-gate column says 'Before recording' rather than 'No evidence', and the no-test-evidence gate excuses it instead of failing it. Phase 1 (auth hardening) is signed off and merged: passwords now use Argon2id and login is rate-limited. Phase 2 (input validation) is in progress with one task blocked on a shared template-escaping decision. Phase 3 (performance) is gated behind Phase 2, and Phase 4 writes down the invariants the audit relied on — documentation work, so it declares no test gate at all. Of five tracked bugs, the logout session leak (BUG-4) is fixed and the cart off-by-one (BUG-3) is being fixed red-first; no high-severity bugs remain unresolved.

**Overall:** 6/13 tasks done · 2/6 phases signed off · 3 open bug(s) · 2 ready now

## P0 — Framework upgrade (done, 2/2)
_The storefront runs on the supported framework line, so the security fixes the audit depends on are actually available._

| id | title | status | model | risk | commit | done | tests | ADO |
|---|---|---|---|---|---|---|---|---|
| P0.1 | Move the app bootstrap onto the new framework entry point | done | sonnet | med | 5e1a77c | 2026-05-27 | before-recording | — |
| P0.2 | Port the route table to the new router API | done | haiku | low | d40b91e | 2026-05-28 | before-recording | — |

## P1 — Auth hardening (done, 2/2)
_Credentials are stored and checked safely: modern password hashing and a rate-limited login path._

| id | title | status | model | risk | commit | done | tests | ADO |
|---|---|---|---|---|---|---|---|---|
| P1.1 | Hash passwords with Argon2id | done | opus | high | 9a1f0c2 | 2026-06-02 | passed | #1421 |
| P1.2 | Rate-limit the login endpoint | done | sonnet | med | b2d7e58 | 2026-06-09 | passed | — |

## P2 — Input validation (in_progress, 1/4)
_Every request payload and user-supplied string is validated or escaped before it reaches business logic or a template._

| id | title | status | model | risk | commit | done | tests | ADO |
|---|---|---|---|---|---|---|---|---|
| P2.1 | Validate the checkout payload | done | sonnet | med | c4a11b9 | 2026-06-23 | passed | — |
| P2.2 | Sanitize the product-search query | in_progress | opus | high | — | started 2026-07-06 | no-evidence | — |
| P2.3 | Escape server-rendered template output | blocked | sonnet | med | — | started 2026-07-13 | failed | — |
| P2.4 | Add zod schemas for cart mutations | pending | haiku | low | — | — | no-evidence | — |

## P3 — Performance pass (pending, 0/2)
_The catalog and product pages render without the known redundant work and heavy above-the-fold images._

| id | title | status | model | risk | commit | done | tests | ADO |
|---|---|---|---|---|---|---|---|---|
| P3.1 | Memoize the product-list selector | pending | haiku | low | — | — | no-evidence | — |
| P3.2 | Lazy-load below-the-fold images | pending | haiku | low | — | — | no-evidence | — |

## BF1 — Bugfix batch 1 (in_progress, 1/2)
_Reported bugs are reproduced red-first and fixed._

| id | title | status | model | risk | commit | done | tests | ADO |
|---|---|---|---|---|---|---|---|---|
| BF1.1 | Fix BUG-3: cart total off-by-one with stacked discounts | in_progress | sonnet | med | — | started 2026-07-20 | no-checks | — |
| BF1.2 | Fix BUG-4: logout leaves the session cookie | done | opus | high | a1b2c3d | 2026-07-21 | passed | — |

## P4 — Documentation (pending, 0/1)
_The invariants Phase 1 and Phase 2 established are written down where the next reader will look for them, so the next audit does not rediscover them._

| id | title | status | model | risk | commit | done | tests | ADO |
|---|---|---|---|---|---|---|---|---|
| P4.1 | Write down the auth and checkout invariants | pending | haiku | low | — | — | no-gate | — |

## Bugs

| id | title | status | severity | task | fixedIn |
|---|---|---|---|---|---|
| BUG-1 | Product images 404 intermittently on Safari | open | med | — | — |
| BUG-2 | Checkout is slow on 3G mobile | triaged | low | — | — |
| BUG-3 | Cart total off-by-one with stacked discounts | in_progress | med | BF1.1 | — |
| BUG-4 | Logout does not clear the session cookie | fixed | high | BF1.2 | a1b2c3d |
| BUG-5 | Dark-mode label contrast below AA | wontfix | low | — | — |

## Ready now

P2.4, P4.1


## Usage

**Total:** 90.1M tokens · ~$102.45 equiv · 1,304 msgs · 5 session(s) · cache hit 93% · rates as of 2026-08-06

### By phase

| phase | tokens | cost | msgs |
|---|---:|---:|---:|
| P0 | 32.7M | $19.80 | 352 |
| P1 | 31.6M | $29.13 | 266 |
| BF1 | 15.5M | $20.18 | 127 |
| P2 | 6.4M | $27.40 | 343 |
| Uncategorized | 3.8M | $5.94 | 216 |

### By model

| model | tokens | cost | msgs |
|---|---:|---:|---:|
| claude-sonnet-5 | 54.8M | $53.24 | 694 |
| claude-opus-5 | 25.8M | $43.96 | 376 |
| claude-haiku-4-5 | 8.8M | $2.48 | 198 |
| claude-fable-5 | 610.5K | $2.77 | 36 |

### By author

| author | tokens | cost | msgs |
|---|---:|---:|---:|
| sara@acme.example | 31.3M | $32.29 | 416 |
| milos@acme.example | 30.7M | $37.40 | 379 |
| alex@acme.example | 28.0M | $32.76 | 509 |

### Month by month

Plan columns count the whole project by event month (task completedAt, bug reportedAt, the linked task's completedAt for a fix, phase mergedAt).

| month | tokens | cost | msgs | tasks done | bugs | fixed | merged |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 33.2M | $20.35 | 388 | 2 | 0 | 0 | 1 |
| 2026-06 | 36.8M | $44.61 | 613 | 3 | 3 | 0 | 1 |
| 2026-07 | 20.0M | $37.49 | 303 | 1 | 2 | 1 | 0 |

### Economics

- **Cache:** 93% hit; the input side bills at 20% of fresh-token rates.
- **Lowest cache phase:** P2 at 62%.
- **Attribution:** 96% of spend attributed (87% to a specific task).
- **Cost per completed task:** $11.41 across 6 task(s).
- **Projection:** remaining 7 task(s) at the p25-p75 rate = $66.23 to $110.21.
- **Retried tasks:** $5.36 across 1 task(s) (5% of spend). Not the same as wasted spend — the ledger buckets by hour, not by attempt.
- **Blocked tasks:** $5.36 across 1 task(s) — spend with no outcome.

### Model cost within each risk band

Compared inside a band on purpose: hard work is routed to the stronger model deliberately, so a raw spend-per-task comparison across bands would flag that working system as a fault.

| risk | model | tasks | cost/task | mean attempts |
|---|---|---:|---:|---:|
| high | claude-opus-5 | 3 | $11.19 | 1.0 |
| med | claude-sonnet-5 | 5 | $10.01 | 1.4 |
| low | claude-haiku-4-5 | 1 | $1.74 | 1.0 |
