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

#### ARCHITECTURE RULING
- Databento remains a strong candidate due to its documented native `pit=True`
  revision support, self-service metered delivery, and $125 free historical
  credit.
- However, Drift will not pay for the annual reference data subscription yet.
  The free evaluation path for Alpaca must be explored first.

---

### 3. Alpaca (Next Evaluation Target)

#### DOCUMENTED (from First-Party Specifications)
- **Free Market Data Tier**: The Basic market data plan is free and provides
  access to historical US equity data back to approximately 2016.
- **Historical SIP Access**: Historical SIP queries older than the 15-minute
  real-time delay window are accessible without requiring a paid live SIP
  subscription.
- **Corporate Actions API**: Supports key action types including cash dividends,
  stock dividends, stock splits, reverse splits, spinoffs, and mergers.
- **Server-Sent Events (SSE) Mutation Stream**: The Corporate Actions SSE stream
  exposes mutation events (`insert`, `update`, `delete`) and supports historical
  replay parameters (`since`, `until`, and event IDs).
- **Point-in-Time Symbology**: Historical stock bars support `asof` symbol mapping
  to retrieve historical data under previous ticker symbols.
- **Asset Metadata**: The Assets API distinguishes active from inactive/delisted
  assets.

#### UNKNOWN (to be investigated in next screening)
- How far back the corporate actions mutation replay stream (`since`/`until`)
  extends in practice.
- Whether old `update` and `delete` events remain retrievable indefinitely or are
  purged after a sliding window.
- Ticker-reuse and permanent security identity fidelity across complex
  restructurings.
- Handling of delisted and OTC securities.
- Point-in-time revision behavior for daily aggregate bars.
- Contractual retention rights for downloaded historical data under Alpaca's
  developer terms.
- Suitability for both `historical_decision_input` and `retrospective_audit`
  purposes.

#### ARCHITECTURE RULING
- Alpaca is designated as the next candidate for empirical screening.
- Testing Alpaca's free path must occur before committing capital to Databento's
  reference subscription.
- No Alpaca account creation, credential generation, or API probing is authorized
  during this documentation task.

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

The immediate next research step in M1e provider evaluation is:
1. Conduct an empirical screening of Alpaca's free historical and corporate
   action APIs using a dedicated sandbox/free account.
2. Specifically test corporate action mutation event replay (`since`/`until`),
   `asof` bar symbol mapping, and asset lifecycle tracking.
3. Compare Alpaca's empirical findings against Databento and algoseek before
   finalizing the M1e Task 8 provider selection.

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
