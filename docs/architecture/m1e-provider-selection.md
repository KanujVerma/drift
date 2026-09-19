# M1e Provider Selection and Screening State

## Status

Active architecture record, 2026-09-19.

This document records the empirical screening, documentary evidence, and
architecture rulings governing the selection of real-source market data providers
for Drift M1e (License-Gated Real-Source Qualification and Replay Closure).

## Core Selection Principle

Drift M1e does not select providers based on a weighted average vendor score or
marketing reputation. Qualification evaluates exact candidate products against
eight strict, non-negotiable hard gates:

1. **M1b-M1d Semantic Coverage**: Security master identity, listed/delisted
   universes, granular corporate action terms, realized session facts, and
   unadjusted/adjusted observations.
2. **Provider Assertion and Revision Fidelity**: The ability to reconstruct what
   the provider asserted as of a past cutoff, distinguishing business-time
   history (when an event happened) from provider revision history (when an
   assertion was published, updated, or corrected).
3. **Historical Availability and Point-in-Time Evidence**: Explicit evidence of
   when records became available to consumers, avoiding lookahead bias.
4. **Internal Quantitative and Trading-Support Rights**: Contractual authorization
   for internal research, backtesting, machine learning, automated non-display
   modeling, and future trading support.
5. **Durable Exact Replay Rights**: Legal authorization to retain the exact native
   source bytes in private local storage for indefinite offline research
   reconstruction, surviving subscription termination or account dormancy.
6. **Acquisition Completeness and Reproducibility**: Closed-world boundary
   definitions, manifests, checksums, and deterministic batch retrieval.
7. **Golden Case Feasibility**: Capacity to supply the operational evidence
   required for the eighteen closed M1e invariant cases (G01 through G18).
8. **Bounded Pilot Practicality**: Self-service accessibility, transparent
   pricing, free sandbox/credit options, and proportionate cost for an initial
   bounded pilot (<=100 securities, <=2 continuous years).

A provider failure at any hard gate is scientific evidence. Drift will not weaken
its domain contracts or research invariants to accommodate vendor limitations.

## Evidence Hierarchy

Claims in this document are strictly classified using four epistemic tiers:

- **DOCUMENTED**: Supported by first-party provider documentation, terms of
  service, published schemas, or official API specifications.
- **EMPIRICALLY OBSERVED**: Directly observed through authenticated API responses,
  sandbox query runs, data payload inspections, or status codes.
- **ARCHITECTURE RULING**: Binding project design decision made by the Drift
  architect.
- **UNKNOWN**: Genuinely unresolved facts requiring empirical testing or
  contractual clarification.

---

## Primary Provider Candidates

### 1. algoseek

#### EMPIRICALLY OBSERVED (via User Sandbox Account)
- **Identity Semantics**: Strong alignment with Drift M1b. Empirical testing
  demonstrated persistent identity across observed ticker and name changes,
  listing and venue transitions, and delisted securities remaining addressable.
  Observed chains associate multiple `SecId` records through a stable `ASID`
  (algoseek Security Identifier) from 2007 onward while maintaining distinct
  identities under ticker reuse.
- **Universe Coverage**: Listed and delisted US equities are addressable with
  explicit start and end dates.
- **Corporate Action Terms**: Adjustment factors, event reasons (e.g.,
  `CashDiv`, `ForwardSplit`, `ReverseSplit`), and effective dates are available.
- **Microstructure and Sessions**: Trade and Quote (TAQ) and minute bars provide
  granular trade condition flags, venue MICs, and timestamps. Trade cancellation
  and correction records exist at the tick layer.
- **Market Events**: Explicit trading halt timestamps, resumption times, halt
  reason codes, and holiday schedules are present.
- **Licensing Structure**: algoseek offers both term leases and an explicit
  commercial "Buy in perpetuity" model allowing indefinite internal retention
  of specified historical datasets.

#### Critical Limitation (EMPIRICALLY OBSERVED)
- **Reference Data Overwrites**: In tested reference tables, later updates and
  revisions (such as updated `ReportDate` or revised corporate action factors)
  overwrite prior historical rows.
- **Absence of Assertion Versions**: No historical release identifiers, vintage
  tags, `as_of` query parameters, or versioned historical snapshots were found
  for reference data.
- **Retroactive Recalculation**: Adjustment factors are recalculated nightly
  going backward. As a result, querying the database today returns the current
  retroactively revised state, not the assertions algoseek made as of an earlier
  historical cutoff.

#### ARCHITECTURE RULING
- algoseek cannot currently serve as the sole first-pilot source for the
  `historical_decision_input` purpose profile. Because freezing data today
  cannot reconstruct historical provider assertions that were overwritten before
  acquisition, it fails Drift's point-in-time revision fidelity gate.
- This is not a vendor-wide rejection. algoseek remains a candidate for:
  - the `retrospective_audit` purpose profile;
  - raw market observation evidence (where trade-level cancels/corrections exist);
  - prospective archival pipelines;
  - multi-source composition where another provider supplies revision history.
- Commercial sales outreach and perpetual-license quote inquiries are paused
  until reference revision mechanisms are clarified or another primary source is
  evaluated.

---

### 2. Databento

#### EMPIRICALLY OBSERVED (via User Free Account)
- **API and Tooling**: Modern, high-performance REST/HTTP and Python client.
- **Market Data Feeds**: Historical market data downloads function as expected.
- **Batch Acquisition Model**: Batch downloads provide uncompressed byte counts,
  deterministic file inventories, and SHA-256 manifests (`condition.json`,
  `metadata.json`, `manifest.json`), mapping directly to Drift's M1e acquisition
  receipt architecture.
- **Venue Status**: Trading status and market event schemas are available on
  relevant venue feeds.
- **Free Account Boundary**: Security Master, Corporate Actions, and Adjustment
  Factors endpoints returned HTTP 403 (Subscription Required) on the free
  account tier.

#### DOCUMENTED (from First-Party Specifications)
- **Point-in-Time Corporate Actions**: The corporate actions dataset features a
  native `pit=True` query parameter documented to retain all historical record
  versions for each event rather than overwriting past values.
- **Revision Metadata**: Schema includes `event_unique_id` and `ts_record`
  (provider receive/insertion timestamp), exposing provider assertion order.
- **Security Master**: Supports `ts_record` and `ts_effective`, separating
  issuer, security, and listing concepts with point-in-time symbology resolution
  (`stype_in`/`stype_out`).
- **Historical Breadth**: Security Master history is documented approximately from
  2005-01-01, while Corporate Actions history is documented approximately from
  2018-05-01. Both exceed or substantially support the bounded M1e pilot
  requirements, though their historical depths differ.

#### UNKNOWN
- Empirical verification of reference-data point-in-time behavior on the paid
  subscription tier.
- Explicit post-subscription exact-byte retention rights under account-specific
  exchange agreements (standard Terms of Use do not contain an express purge
  mandate, but explicit perpetual retention is not affirmative).
- Exact order-form and pricing terms for the standalone reference plan.

##### ARCHITECTURE RULING
- Databento remains the leading candidate for future promotion-grade
  qualification due to its documented native `pit=True` revision support,
  `event_unique_id`, `ts_record`, Security Master temporal intervals, and
  deterministic batch manifests with SHA-256 inventories.
- However, Drift will not pay for the annual reference data subscription yet.
  Paid promotion-grade source qualification is deferred until exploratory
  research produces a strategy candidate sufficiently promising to justify that
  capital expenditure.
- No immediate Databento outreach or purchase is required.

---

### 3. Alpaca (Preferred Free Development Source)

#### EMPIRICALLY OBSERVED (via User Free Basic Account)

##### Strengths
- **Free Basic and Paper Account**: Authenticated access verified across paper
  trading account and historical market data feeds with zero subscription cost.
- **Historical SIP Market Data**: Historical SIP queries older than the
  15-minute real-time delay window are fully accessible on the free plan,
  retrieving historical trades and bars across multiple years (e.g., 2021, 2022,
  2024).
- **Microstructure Fidelity**: Raw historical trades include nanosecond UTC
  timestamps (`t`), exchange codes (`x`), trade condition arrays (`c`), trade
  sequence IDs (`i`), and tape indicators (`z`).
- **Rich Corporate Actions REST**: All 17 documented action types are accessible.
  Empirically verified cases include:
  - *Name change*: FB -> META (`old_symbol: FB`, `new_symbol: META`,
    `process_date: 2022-06-09`).
  - *Forward split*: NVDA 10-for-1 split (`old_rate: 1`, `new_rate: 10`,
    `ex_date: 2024-06-10`, `due_bill_redemption_date: 2024-06-10`).
  - *Reverse split*: GE 1-for-8 split (`old_rate: 8`, `new_rate: 1`,
    `ex_date: 2021-08-02`, CUSIP change from `369604103` to `369604301`).
  - *Cash mergers*: TWTR ($54.20/share, 2022-10-28) and ATVI ($95.00/share,
    2023-10-13).
  - *Stock merger*: XLNX/AMD (1.7234 AMD per 1 XLNX, 2022-02-14).
  - *Stock-and-cash merger*: AAIC/EFC (0.3619 EFC + $0.09 cash, 2023-12-14).
  - *Spin-offs*: GE spin-offs of GEHC (2023-01-04) and GEV (2024-04-02).
  - *Worthless removals*: Explicit records with process dates and CUSIPs.
  - *Due-bill dates*: Explicitly returned on splits and spin-offs.
- **Point-in-Time Symbology (`asof`)**: Historical stock bars support `asof`
  symbol mapping. Querying `META` with `asof=2022-05-01` correctly returns the
  Roundhill Metaverse ETF ($12.31 price level) rather than Facebook, proving
  that ticker reuse can be distinguished when `asof` is explicitly supplied.
  Querying with `asof=-` cleanly disables symbol mapping.
- **Share Classes**: `BRK.A` and `BRK.B` are maintained as clearly separate
  assets with distinct UUIDs, distinct symbols, and independent bar series.
- **Inactive/Delisted Terminal Discovery**: Delisted securities remain queryable
  in Assets API under their terminal symbols (`TWTR`, `XLNX`, `BBBYQ`, `SIVBQ`).
- **Session Schedules**: The `/v2/calendar` endpoint explicitly records
  scheduled market sessions, settlement dates, and scheduled early closes (e.g.,
  2024-07-03 closing at 13:00).

##### Critical Limitations
- **Corporate Action Mutation Replay Truncation**: The SSE corporate action
  mutation stream (`/v1beta1/events/corporate-actions`) was empirically probed
  across historical windows. While it exposes `insert` and `update` mutations
  with stable ULID event IDs and publication timestamps (`at`), the earliest
  retained mutation event found is `2026-07-09T09:00:05Z`. The effective retained
  history during screening was approximately 72 days (~10 weeks); all older
  historical queries returned zero events. Alpaca cannot reconstruct provider
  corporate action assertion history across a standard 1-2 year historical
  research window.
- **Derived Observation Vintages**: Daily and minute bars return current derived
  values. Alpaca provides no historical provider-vintage or `ts_record` history
  (`pit=true` returns HTTP 400).
- **Identity Gaps**: Omitting `asof` retroactively projects current ticker
  identities backward. Historical venue transfer intervals are absent.
  Delisted listed-to-OTC symbols overwrite original tickers in place, causing
  queries for original listed symbols (`SIVB`, `BBBY`) to return HTTP 404.
- **Absent Trading Halts**: Endpoints for trading halts (`/v2/stocks/halts`,
  `/v1beta1/stocks/halts`) returned HTTP 404. Halts cannot be distinguished from
  zero-trade periods without independent external truth.
- **Acquisition Receipts**: REST pagination and SSE streams require Drift-side
  receipting (`AcquisitionReceiptV1`); no vendor-generated immutable batch
  manifest exists.

#### ARCHITECTURE RULING
- Alpaca cannot currently serve as the sole promotion-grade source for the M1e
  `historical_decision_input` purpose profile because its corporate action
  mutation replay is truncated to ~72 days, derived bars lack vintages, and
  trading halts are absent.
- This is NOT a vendor-wide rejection. Under ADR 0012, Alpaca becomes the
  current preferred **FREE DEVELOPMENT** source for exploratory evaluation
  because:
  - subscription cost is zero;
  - historical SIP trades and bars are richly accessible;
  - corporate action schemas are comprehensive;
  - paper account credentials exist;
  - APIs are practical for building and pressure-testing evaluator mechanics.
- Alpaca is explicitly NOT M1e-qualified. Its known data limitations must remain
  explicit, and exploratory results generated with Alpaca data are strictly
  non-promotable.

---

## Eliminated Standard Profiles

The following standard consumer/commercial offerings have been evaluated and
eliminated from consideration as primary M1e sources under their default terms:

| Provider | Critical Disqualifier | Reference Clause |
|---|---|---|
| **Nasdaq Data Link (Sharadar)** | Mandatory complete raw data purge and destruction upon subscription termination. | Standard Data License Terms, Section 8 (Termination and Purge Certification). |
| **Norgate Data** | Mandatory deletion of all Content and Information upon subscription expiration; no point-in-time revision tracking. | Norgate Data EULA, Section 5 (Termination). |
| **Tiingo** | Explicit requirement to promptly and permanently delete all data from all systems, storage, and backups upon plan termination or downgrade. | Tiingo Terms of Use, Section 6 (Termination and Deletion). |
| **Massive / Polygon.io** | Standard developer terms prohibit non-display automated trading/strategy creation and mandate market data deletion upon termination. | Massive Market Data Terms of Service (Post-Termination Obligations). |

These eliminations apply strictly to the standard terms reviewed. They do not
preclude custom negotiated enterprise agreements if such options are ever
authorized.

---

## Canonical Next Action

Under ADR 0012, paid promotion-grade M1e qualification is deferred until
economically justified by exploratory research.

The immediate next project action is:
1. Conduct the external architecture and design pass for the **M2 Evaluator**,
   defining the provider-neutral evaluator core and its two distinct evaluation
   lanes (`EXPLORATORY` and `PROMOTION`).
2. Formulate the executable M2 implementation plan.
3. Implement the evaluator core and exploratory Alpaca development adapter
   strictly within the exploratory lane.

## External Reference Links

- **Alpaca Data API**: https://alpaca.markets/data
- **Alpaca Market Data FAQ**: https://docs.alpaca.markets/us/docs/market-data-faq
- **Alpaca Corporate Actions SSE**: https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse
- **Alpaca Historical Stock Bars**: https://docs.alpaca.markets/us/reference/stockbarsingle-1
- **Alpaca Assets API**: https://docs.alpaca.markets/us/reference/get-v2-assets-1
- **Databento Corporate Actions**: https://databento.com/docs/venues-and-datasets/corporate-actions
- **Databento Security Master**: https://databento.com/security-master
- **algoseek Documentation**: https://algoseek.com/docs/license
- **algoseek Sandbox**: https://algoseek.com/sandbox/
