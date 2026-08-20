# ACME Store — security & correctness audit

repo: acme-store · generated 2026-08-20 09:33 UTC

> Phase 1 (auth hardening) is signed off and merged: passwords now use Argon2id and login is rate-limited. Phase 2 (input validation) is in progress with one task blocked on a shared template-escaping decision. Phase 3 (performance) is gated behind Phase 2. Of five tracked bugs, the logout session leak (BUG-4) is fixed and the cart off-by-one (BUG-3) is being fixed red-first; no high-severity bugs remain unresolved.

**Overall:** 4/10 tasks done · 1/4 phases signed off · 3 open bug(s) · 1 ready now

## P1 — Auth hardening (done, 2/2)
_Credentials are stored and checked safely: modern password hashing and a rate-limited login path._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| P1.1 | Hash passwords with Argon2id | done | opus | high | 9a1f0c2 | 2026-06-02 | #1421 |
| P1.2 | Rate-limit the login endpoint | done | sonnet | med | b2d7e58 | 2026-06-09 | — |

## P2 — Input validation (in_progress, 1/4)
_Every request payload and user-supplied string is validated or escaped before it reaches business logic or a template._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| P2.1 | Validate the checkout payload | done | sonnet | med | c4a11b9 | 2026-06-23 | — |
| P2.2 | Sanitize the product-search query | in_progress | opus | high | — | started 2026-07-06 | — |
| P2.3 | Escape server-rendered template output | blocked | sonnet | med | — | started 2026-07-13 | — |
| P2.4 | Add zod schemas for cart mutations | pending | haiku | low | — | — | — |

## P3 — Performance pass (pending, 0/2)
_The catalog and product pages render without the known redundant work and heavy above-the-fold images._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| P3.1 | Memoize the product-list selector | pending | haiku | low | — | — | — |
| P3.2 | Lazy-load below-the-fold images | pending | haiku | low | — | — | — |

## BF1 — Bugfix batch 1 (in_progress, 1/2)
_Reported bugs are reproduced red-first and fixed._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| BF1.1 | Fix BUG-3: cart total off-by-one with stacked discounts | in_progress | sonnet | med | — | started 2026-07-20 | — |
| BF1.2 | Fix BUG-4: logout leaves the session cookie | done | opus | high | a1b2c3d | 2026-07-21 | — |

## Bugs

| id | title | status | severity | task | fixedIn |
|---|---|---|---|---|---|
| BUG-1 | Product images 404 intermittently on Safari | open | med | — | — |
| BUG-2 | Checkout is slow on 3G mobile | triaged | low | — | — |
| BUG-3 | Cart total off-by-one with stacked discounts | in_progress | med | BF1.1 | — |
| BUG-4 | Logout does not clear the session cookie | fixed | high | BF1.2 | a1b2c3d |
| BUG-5 | Dark-mode label contrast below AA | wontfix | low | — | — |

## Ready now

P2.4


## Usage

**Total:** 93.1M tokens · ~$103.65 equiv · 899 msgs · 4 session(s) · cache hit 94% · rates as of 2026-08-06

### By phase

| phase | tokens | cost | msgs |
|---|---:|---:|---:|
| BF1 | 50.1M | $36.16 | 118 |
| P1 | 30.8M | $28.22 | 259 |
| P2 | 7.5M | $32.53 | 328 |
| Uncategorized | 4.6M | $6.74 | 194 |

### By model

| model | tokens | cost | msgs |
|---|---:|---:|---:|
| claude-opus-5 | 52.4M | $60.80 | 356 |
| claude-sonnet-5 | 38.1M | $39.12 | 421 |
| claude-haiku-4-5 | 2.0M | $0.75 | 85 |
| claude-fable-5 | 655.2K | $2.98 | 37 |

### By author

| author | tokens | cost | msgs |
|---|---:|---:|---:|
| milos@acme.example | 47.8M | $48.06 | 246 |
| alex@acme.example | 25.3M | $31.74 | 479 |
| sara@acme.example | 20.0M | $23.85 | 174 |

### Month by month

Plan columns count the whole project by event month (task completedAt, bug reportedAt, the linked task's completedAt for a fix, phase mergedAt).

| month | tokens | cost | msgs | tasks done | bugs | fixed | merged |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-06 | 38.1M | $47.47 | 640 | 3 | 3 | 0 | 1 |
| 2026-07 | 55.0M | $56.18 | 259 | 1 | 2 | 1 | 0 |

### Economics

- **Cache:** 94% hit; the input side bills at 18% of fresh-token rates.
- **Lowest cache phase:** P2 at 62%.
- **Attribution:** 95% of spend attributed (88% to a specific task).
- **Cost per completed task:** $15.77 across 4 task(s).
- **Projection:** suppressed — needs 5 completed tasks, has 4.
- **Retried tasks:** $5.82 across 1 task(s) (6% of spend). Not the same as wasted spend — the ledger buckets by hour, not by attempt.
- **Blocked tasks:** $5.82 across 1 task(s) — spend with no outcome.

### Model cost within each risk band

Compared inside a band on purpose: hard work is routed to the stronger model deliberately, so a raw spend-per-task comparison across bands would flag that working system as a fault.

| risk | model | tasks | cost/task | mean attempts |
|---|---|---:|---:|---:|
| high | claude-opus-5 | 3 | $16.69 | 1.0 |
| med | claude-sonnet-5 | 4 | $9.50 | 1.5 |
