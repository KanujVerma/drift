# Stage 1 G1: Alpaca SIP qualification status

**Status: BLOCKED.** This page does not establish account-specific data access,
research or retention rights, complete historical coverage, or acceptance of
Alpaca SIP for the study. No historical study result follows from this page.

An earlier version of this report asserted that those checks had succeeded, but
also described fail-closed handling for HTTP 401 responses and unresolved legal
agreements. It did not identify original account-specific evidence supporting
the affirmative claims. The earlier text remains in Git history; its assertions
must not be used as qualification evidence. Synthetic receipts and mock coverage
records are engineering fixtures, not evidence of provider origin or rights.

## Locked study requirements

The [Stage 1 protocol](../stage1-g3-protocol-v1.md) fixes the twelve instruments:
VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD and GLD. It specifies
development in 2021 through 2023, validation in 2024, and retrospective
discovery in 2025. It also requires at least 253 completed warmup sessions and
126 completed observation intervals before scoring. These are requirements,
not verified provider coverage or a generated session calendar.

## Evidence needed to unblock G1

The producer must retain and independently verify evidence for the exact
account, dataset, dates and intended use, including:

- Provider and subscriber identity, the applicable agreements, entitlement,
  permitted research use and private retention. Public documentation or an API
  response alone does not establish the account's contractual rights.
- Original, privately retained source responses and authenticated acquisition
  receipts, including feed, request parameters, retrieval time, source vintage,
  pagination and completeness. Raw provider bytes must not be committed to Git.
- Point-in-time security and listing identities, venue calendars, eligible
  sessions, raw prices, corporate actions and distributions, availability
  cutoffs, gaps and revisions for every instrument and required period.
- Enough preceding eligible history for the locked warmup and observation
  windows, with the actual calendar and original data rather than estimated
  session counts.
- A separately reviewed treatment of execution prices, analytical adjustments,
  cash distributions and costs, backed by the original data and contracts.

The earlier report's claims about free historical SIP entitlement, continuous
coverage, corporate-action completeness and permission for offline retention
remain unverified for this study. Do not substitute IEX data, inferred rights,
synthetic records or a successful fixture run for the missing evidence.
[Source qualification issue #378](https://github.com/KanujVerma/drift/issues/378)
tracks the platform source contract. A completed source contract or a passing
code check alone does not admit the dataset; the original evidence and
independent acceptance remain necessary.
