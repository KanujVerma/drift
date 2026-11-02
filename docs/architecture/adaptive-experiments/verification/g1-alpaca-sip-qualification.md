# Drift Stage 1 (G1): Free Historical Alpaca SIP Qualification Report

## 1. Executive Summary and Authority

This audit establishes the empirical and contractual verification of free historical Alpaca consolidated SIP market data access for Drift Stage 1 (G1), covering the exact 12-ETF primary cohort across warmup (2019–2020), development (2021–2023), validation (2024), and retrospective evaluation (2025).

It verifies:
1. **Free Historical SIP Access:** Alpaca Market Data v2 allows full 100% consolidated tape access (`feed=sip`) on the free Basic tier for historical queries ending at least 15 minutes before request time. Older historical data does **not** require an IEX-only feed.
2. **Exact 12-ETF Universe:** Uninterrupted historical coverage for `VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD, GLD`.
3. **Original Source Provenance:** Verified raw execution prices, daily timeframe, deterministic timestamps, and content-addressed payload integrity.
4. **Corporate-Action Completeness:** Verified dividend distribution schedules, split adjustments, single-count accounting on ex-date, and closed-world coverage records.
5. **Contractual Research and Retention Rights:** Permitted internal non-display algorithmic research and private offline retention outside Git; strictly prohibited public redistribution.
6. **Robinhood Gold Nasdaq TotalView Disqualification:** Consumer display entitlement does not authorize extraction into Drift, lacks historical audit tapes, and is excluded from the G1 critical path. Intraday order-book data is deferred to a separate execution-cost study.

---

## 2. Free Historical Alpaca SIP Access Verification

### 2.1 The 15-Minute Rule on Free Basic Tier
Alpaca's Market Data API provides two distinct feeds:
* `feed=sip`: 100% consolidated tape across all US exchanges (CTA Network A/B and UTP Plan).
* `feed=iex`: ~2.5% market share (Investors Exchange only).

Under Alpaca's pricing rules:
* **Real-time SIP data (< 15 minutes old)** requires an Algo Trader Plus or paid subscription.
* **Historical SIP data (`feed=sip`)** is accessible on the **Free Basic Tier** provided that the query's `end` timestamp is at least 15 minutes in the past (`request_end <= request_time - 15 minutes`).
* If a request with `feed=sip` specifies an `end` within the last 15 minutes (or omits `end` on real-time endpoints), the API returns HTTP 403: `{"message": "subscription does not permit querying recent SIP data"}`.

### 2.2 Older Historical Data Does NOT Require IEX-Only Feed
For Drift's historical research windows:
* Development: `2021-01-01` to `2023-12-31` (ended > 2 years in past).
* Validation: `2024-01-01` to `2024-12-31` (ended > 1 year in past).
* Retrospective Evaluation: `2025-01-01` to `2025-12-31` (ended > 10 months in past).

Because all historical requests end well beyond 15 minutes in the past, **`feed=sip` is 100% accessible under the free plan**. Drift does **not** need to fall back to an IEX-only feed for older historical data. An IEX-only assumption for historical data is an artificial and unnecessary degradation of market coverage.

---

## 3. Exact 12-ETF Primary Cohort Coverage

The canonical 12-ETF cohort is immutable and evaluated in fixed order:
`VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD, GLD`

| Ticker | Asset Class | Primary Venue | MIC | Inception Date | Pre-2021 Warmup Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VOO** | Large-Cap US Equity (S&P 500) | NYSE Arca | ARCX | 2010-09-07 | 100% Covered |
| **IJH** | Mid-Cap US Equity (S&P MidCap 400) | NYSE Arca | ARCX | 2000-05-22 | 100% Covered |
| **IJR** | Small-Cap US Equity (S&P SmallCap 600) | NYSE Arca | ARCX | 2000-05-22 | 100% Covered |
| **QQQ** | Nasdaq-100 Large-Cap Equity | Nasdaq | XNAS | 1999-03-10 | 100% Covered |
| **VEA** | Developed Markets Ex-US Equity | NYSE Arca | ARCX | 2007-07-20 | 100% Covered |
| **VWO** | Emerging Markets Equity | NYSE Arca | ARCX | 2005-03-04 | 100% Covered |
| **SHY** | 1–3 Year US Treasury Bonds | Nasdaq | XNAS | 2002-07-22 | 100% Covered |
| **IEF** | 7–10 Year US Treasury Bonds | Nasdaq | XNAS | 2002-07-22 | 100% Covered |
| **TLT** | 20+ Year US Treasury Bonds | Nasdaq | XNAS | 2002-07-22 | 100% Covered |
| **TIP** | US Treasury Inflation-Protected (TIPS) | NYSE Arca | ARCX | 2003-12-04 | 100% Covered |
| **LQD** | iBoxx Investment Grade Corporate Bonds | NYSE Arca | ARCX | 2002-07-22 | 100% Covered |
| **GLD** | SPDR Gold Trust | NYSE Arca | ARCX | 2004-11-18 | 100% Covered |

### Historical Windows:
* **Common Warmup:** 253 completed trading sessions + 126 observation intervals (October 1, 2019 to December 31, 2020). Every instrument launched between 1999 and 2010, so all have full pre-warmup trading history.
* **Development Window:** January 1, 2021 to December 31, 2023 (754 sessions).
* **Validation Window:** January 1, 2024 to December 31, 2024 (252 sessions).
* **Evaluation Window:** January 1, 2025 to December 31, 2025 (250 sessions).

---

## 4. Original Source Provenance

* **Provider Identity:** Alpaca Securities LLC (`data.alpaca.markets`, `paper-api.alpaca.markets`).
* **Endpoint Specifications:**
  * Daily bars: `/v2/stocks/bars?symbols=...&timeframe=1Day&feed=sip&adjustment=raw&start=...&end=...`
  * Calendar: `/v2/calendar?start=...&end=...`
  * Corporate actions: `/v2/corporate-actions?symbols=...&types=cash_dividend,forward_split,reverse_split,unit_split,stock_dividend,spin_off&start=...&end=...`
* **Price Basis Integrity:** Raw execution prices are used for order fills, marks, and portfolio cash accounting. Split/dividend adjusted return series are used strictly for analytical strategy indicators.
* **Session Boundaries:** Regular market session (09:30–16:00 America/New_York). Decisions are evaluated at regular close; executed at the next regular session open.

---

## 5. Corporate-Action Completeness and Accounting

* **Distributions:**
  * Equity ETFs (VOO, IJH, IJR, QQQ, VEA, VWO) pay quarterly distributions.
  * Fixed Income ETFs (SHY, IEF, TLT, TIP, LQD) pay monthly distributions.
  * Gold trust (GLD) has sponsor fee share-reduction mechanisms rather than cash dividends.
* **Single-Count Accounting Rule:** Cash dividends affect account cash on ex-date / payable date exactly once. Adjusted close prices never silently substitute for execution fills.
* **Closed-World Corporate Action Coverage:** Each response is bound to `ClosedWorldCorporateActionCoverageV1` per cohort member. A date range with missing corporate action coverage halts evaluation rather than assuming absence of actions.

---

## 6. Contractual Research and Retention Rights

* **Internal Research Use:** Permitted under Alpaca API terms of service and standard developer terms for personal and algorithmic backtesting, model training, and non-display simulation.
* **Private Local Retention:** Permitted in private directories outside Git (`.local-artifacts` or private storage roots) for reproducible replay and deterministic reconstruction.
* **Public Redistribution Prohibited:** Under exchange agreements (CTA/UTP, NASDAQ OMX Global Subscriber Agreement, NYSE Display Services), redistribution of raw or derived market data to third parties or committing raw provider bytes to public Git repositories is strictly prohibited. Drift complies by keeping raw payload bytes in private storage and checking in only cryptographic SHA-256 digests and manifests.

---

## 7. Robinhood Gold Nasdaq TotalView Disqualification & Exclusion

### 7.1 Why Robinhood Gold TotalView Is Disqualified from G1
1. **Consumer Display Entitlement:** Robinhood Gold's Nasdaq TotalView Level II display is a personal, non-professional interactive visual display feature provided in the Robinhood consumer mobile and web applications.
2. **Unauthorized Programmatic Extraction:** Robinhood's Terms of Service and Customer Agreements explicitly prohibit automated scraping, reverse-engineering, programmatic extraction, or ingestion into third-party algorithmic trading systems or research platforms like Drift.
3. **No Historical Audit Archive:** Robinhood Gold Level II displays live order book depth for current market sessions. It provides no historical depth archives, tick-by-tick order book replays, or point-in-time reconstructible data for the 2019–2025 research windows.
4. **Exclusion from G1 Critical Path:** Robinhood Gold Level II is formally disqualified and excluded from the G1 market data admission path.

### 7.2 Intraday Execution-Cost Study Boundary
Any future study of order-book microstructure, bid-ask spread dynamics, or execution slippage will use properly licensed institutional historical order-book feeds (such as direct Nasdaq TotalView ITCH or Databento Level 3 / Level 2 historical data) within a separate, dedicated intraday execution-cost study, without blocking or contaminating the daily Stage 1 G1 evaluation.
