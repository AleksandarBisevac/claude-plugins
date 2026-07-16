# ACME Store — security & correctness audit

repo: acme-store · generated 2026-07-16 16:06 UTC

> Phase 1 (auth hardening) is signed off and merged: passwords now use Argon2id and login is rate-limited. Phase 2 (input validation) is in progress with one task blocked on a shared template-escaping decision. Phase 3 (performance) is gated behind Phase 2. Of five tracked bugs, the logout session leak (BUG-4) is fixed and the cart off-by-one (BUG-3) is being fixed red-first; no high-severity bugs remain unresolved.

**Overall:** 4/10 tasks done · 1/4 phases signed off · 3 open bug(s) · 1 ready now

## P1 — Auth hardening (done, 2/2)
_Credentials are stored and checked safely: modern password hashing and a rate-limited login path._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| P1.1 | Hash passwords with Argon2id | done | sonnet | high | 9a1f0c2 | 2026-06-28 | #1421 |
| P1.2 | Rate-limit the login endpoint | done | sonnet | med | b2d7e58 | 2026-06-29 | — |

## P2 — Input validation (in_progress, 1/4)
_Every request payload and user-supplied string is validated or escaped before it reaches business logic or a template._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| P2.1 | Validate the checkout payload | done | sonnet | med | c4a11b9 | 2026-07-01 | — |
| P2.2 | Sanitize the product-search query | in_progress | sonnet | high | — | started 2026-07-02 | — |
| P2.3 | Escape server-rendered template output | blocked | sonnet | med | — | started 2026-07-02 | — |
| P2.4 | Add zod schemas for cart mutations | pending | sonnet | low | — | — | — |

## P3 — Performance pass (pending, 0/2)
_The catalog and product pages render without the known redundant work and heavy above-the-fold images._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| P3.1 | Memoize the product-list selector | pending | sonnet | low | — | — | — |
| P3.2 | Lazy-load below-the-fold images | pending | sonnet | low | — | — | — |

## BF1 — Bugfix batch 1 (in_progress, 1/2)
_Reported bugs are reproduced red-first and fixed._

| id | title | status | model | risk | commit | done | ADO |
|---|---|---|---|---|---|---|---|
| BF1.1 | Fix BUG-3: cart total off-by-one with stacked discounts | in_progress | sonnet | med | — | started 2026-07-03 | — |
| BF1.2 | Fix BUG-4: logout leaves the session cookie | done | sonnet | high | a1b2c3d | 2026-07-03 | — |

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
