# Drift M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Design Specification

Date: 2026-09-19. Status: Canonical architecture design specification for Drift M2.
Canonical Baseline: Commit `ef24c2c` (and underlying verified Task 7 checkpoint at `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`).
Related Architecture Decisions: [ADR 0010](../../adr/0010-qualify-real-source-rights-and-replay-before-evaluation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

---

## 1. Objective

M2 constructs the deterministic evaluation and portfolio accounting kernel that powers all quantitative research, strategy screening, and model comparison across Drift.

The evaluator answers one central question:

> Given one exact strategy version, one exact evaluation protocol, one exact evidence lane, one exact provider-neutral historical input bundle, and one exact set of accounting and execution assumptions, what sequence of decisions, fills, economic effects, portfolio states, and resulting wealth occurred?

M2 makes that answer:
- **Deterministic**: Bitwise reproducible across identical inputs, code, and environments.
- **Content-addressed**: Identified by canonical hashing of all constituent parameters, artifacts, and traces.
- **Replayable**: Verifiable offline without network access or non-deterministic state.
- **Temporally causal**: Structurally protected against forward-looking leakage, same-bar lookahead, and unannounced corporate actions.
- **Provider-neutral**: Completely decoupled from vendor schemas, raw payloads, or proprietary APIs.
- **Audit-friendly**: Emitting a granular, content-addressed ledger trace of every phase, mark, fill, cash flow, and valuation.
- **Structurally protected against evidence laundering**: Structurally incapable of upgrading exploratory development results into promotion-grade validation evidence.

M2 is an accounting and evaluation engine, not a statistical summary package. Advanced statistical scorecards (M5), structured research memory (M6), and strategy tournament promotion gates (M10/M11) consume M2 traces rather than living inside M2.

---

## 2. Scope and V1 Domain Boundaries

M2 V1 establishes a rigorous, minimal accounting kernel strictly bounded to regular daily trading sessions for US cash equities.

### 2.1 Admitted Scope (V1)
- **Asset Class**: US cash equities (common stocks, ETFs, American Depositary Receipts admitted through M1b).
- **Session Resolution**: Regular daily trading sessions only (`SessionScope.REGULAR`, 09:30 to 16:00 US/Eastern).
- **Decision Resolution**: Daily, session-by-session evaluation cycles.
- **Currency**: Single-currency USD cash accounting.
- **Portfolio Constraint**: Fully funded, long-only equity holdings (cash balance >= 0, share quantities >= 0).
- **Position Quantities**: Whole-share integers only.
- **Corporate Action Economics**: First-class M1c economic actions (splits, dividends, spin-offs, mergers, liquidations, terminations).
- **Execution**: Target whole-share deltas filled at the next eligible regular-session open.
- **Pricing Basis**: Source-basis unadjusted prices for accounting, marks, and fills.

### 2.2 Explicitly Excluded Scope (V1 Hard Boundaries)
Attempts to evaluate configurations outside this admitted domain fail closed with explicit validation errors:
- **No Intraday Execution**: No intraday bar clocks, tick execution, TWAP/VWAP engines, or minute-level scheduling.
- **No Shorting or Margin**: No negative share balances, borrowing fees, margin calls, or leverage calculations. Attempts to emit negative target positions are rejected.
- **No Fractional Shares**: Whole shares only; fractional allocations cannot be synthesized or rounded silently by the accounting engine.
- **No Options or Derivatives**: Cash equities only; warrants, rights, and convertibles with unsupported property terms fail closed.
- **No Multi-Currency**: Single currency (USD) cash accounting only.
- **No Tax Accounting**: Wash sales, tax-lot identification (FIFO/LIFO/HIFO), and capital gains tax liabilities are execution/tax concerns outside M2.
- **No Live Brokerage or Order Submission**: M2 contains zero network access, broker adapters, or order placement mechanisms.

---

## 3. Two-Lane Architecture (ADR 0012)

In accordance with ADR 0012, Drift maintains exactly ONE provider-neutral evaluator core engine operating across two structurally segregated evidence lanes:

```
+-----------------------------------------------------------------------------------+
|                                Drift Evaluator Core                               |
|                                                                                   |
|  - Provider-neutral domain contracts only (M0-M1d)                                |
|  - Causal session clock (Post-Close Decision -> Next Open Fill)                  |
|  - Source-basis unadjusted accounting + M1c corporate action processing           |
|  - 5-phase deterministic session schedule                                         |
|  - Pure runtime strategy interface (Decision Context -> Whole-Share Intent)       |
|  - Content-addressed execution trace & scientific classification                  |
+-----------------------------------------------------------------------------------+
                                         ^
                                         | Consumes
        +--------------------------------+--------------------------------+
        |                                                                 |
+------------------------------------+          +------------------------------------+
|          EXPLORATORY Lane          |          |           PROMOTION Lane           |
|                                    |          |                                    |
| - Purpose: Prototyping, baselines, |          | - Purpose: Champion/challenger     |
|   signal screening, engineering.   |          |   tournaments, live gating.        |
| - Input: Free development data     |          | - Input: Positive M1e qualified    |
|   (Alpaca Basic).                  |          |   sources (e.g. Databento PIT).    |
| - Limitation: Binds explicit known |          | - Requirement: Verified rights,    |
|   flaws (truncated CA replay, etc).|          |   native bytes, offline replay.    |
| - Epistemic Status: Strictly       |          | - Epistemic Status: Certified      |
|   NON-PROMOTABLE forever.          |          |   promotion-grade evidence.        |
+------------------------------------+          +------------------------------------+
```

### 3.1 Exploratory Development Lane (`EXPLORATORY`)
- **Purpose**: Fast, cost-free engineering verification, baseline establishment (M3), signal exploration, and preliminary hypothesis screening.
- **Authorized Input**: Free development data (default: Alpaca Basic historical SIP bars and REST corporate actions).
- **Known Limitations**: Input bundles carry explicit documented limitations (e.g. truncated corporate action mutation history, unversioned derived bars, missing trading halt telemetry).
- **Epistemic Constraint**: Results are strictly non-promotable. They cannot be submitted to champion/challenger tournaments (M10), overfitting gates (M11), or live execution approval (M16+).

### 3.2 Promotion-Grade Lane (`PROMOTION`)
- **Purpose**: Authoritative empirical validation for strategy promotion and production deployment gating.
- **Authorized Input**: Datasets produced exclusively by a fully qualified, positively verified M1e real-source profile.
- **Qualification Requirements**: Every critical required dimension must PASS, exact native bytes must be retained in private storage, rights must authorize internal algorithmic use and indefinite offline retention, and offline replay closure must verify bitwise identical output.
- **Current Operational Status**: Paused/deferred under ADR 0012. Tested in M2 exclusively through synthetic qualification fixtures to verify fail-closed enforcement.

---

## 4. Structural Anti-Upgrade Enforcement

To guarantee that exploratory evidence cannot be laundered into promotion-grade claims, lane separation is enforced at the type and schema layer, not via a mutable boolean flag.

### 4.1 Invariant: No Mutable Lane Field
An evaluation run cannot be toggled from exploratory to promotion by flipping a flag (e.g. `is_promotable = True`).

### 4.2 Acyclic Admission Dependency Graph
The relationship between market data input bundles, admissions, and evaluation runs is strictly acyclic:
$$\text{Market Data} \longrightarrow \text{EvaluationInputBundleV1} (\text{bundle\_hash}) \longrightarrow \text{EvaluationAdmissionV1} (\text{input\_bundle\_hash} = \text{bundle\_hash}) \longrightarrow \text{EvaluationRunIdentity}$$

`EvaluationInputBundleV1` does NOT hold a reference to `admission_hash`. The input bundle is immutable historical evidence independent of the evaluation lane under which it is evaluated. The admission token authorizes the bundle.

### 4.3 Distinct Immutable Admission and Result Types
The domain model enforces disjoint type hierarchies:

```python
class ExploratoryEvaluationAdmissionV1(FrozenModel):
    """Admission proof for exploratory evaluation using development-grade data."""

    schema_version: Literal["1"] = "1"
    admission_id: UUID7
    lane: Literal["exploratory"] = "exploratory"
    development_source_profile_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    acknowledged_limitations: tuple[NonBlankStr, ...]
    admitted_at: UTCDateTime
    admission_hash: SHA256Hash


class PromotionEvaluationAdmissionV1(FrozenModel):
    """Admission proof strictly requiring verified M1e qualification evidence."""

    schema_version: Literal["1"] = "1"
    admission_id: UUID7
    lane: Literal["promotion"] = "promotion"
    m1e_qualification_report_hash: SHA256Hash
    m1e_purpose: Literal["historical_decision_input"]
    m1e_snapshot_hash: SHA256Hash
    m1e_rights_assessment_hash: SHA256Hash
    m1e_replay_result_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    admitted_at: UTCDateTime
    admission_hash: SHA256Hash


type EvaluationAdmissionV1 = Annotated[
    ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1,
    Field(discriminator="lane"),
]


class EvaluationSummaryMetricsV1(FrozenModel):
    """Raw deterministic accounting metrics summary emitted by the evaluator core."""

    initial_cash: Decimal
    ending_cash: Decimal
    ending_holdings_value: Decimal
    ending_pending_claims_value: Decimal
    ending_net_asset_value: Decimal
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
    total_turnover_notional: Decimal
    total_fill_count: int
    total_session_count: int
    daily_equity_series: tuple[tuple[date, Decimal], ...]


class ExploratoryEvaluationResultV1(FrozenModel):
    """Immutable exploratory evaluation result; permanently non-promotable."""

    schema_version: Literal["1"] = "1"
    result_id: UUID7
    run_id: UUID7
    lane: Literal["exploratory"] = "exploratory"
    admission: ExploratoryEvaluationAdmissionV1
    evaluation_hash: SHA256Hash
    trace_hash: SHA256Hash
    classification: EvaluationClassification
    summary_metrics: EvaluationSummaryMetricsV1
    completed_at: UTCDateTime

    @property
    def is_promotable(self) -> bool:
        return False


class PromotionEvaluationResultV1(FrozenModel):
    """Immutable promotion evaluation result; verified against M1e qualification."""

    schema_version: Literal["1"] = "1"
    result_id: UUID7
    run_id: UUID7
    lane: Literal["promotion"] = "promotion"
    admission: PromotionEvaluationAdmissionV1
    evaluation_hash: SHA256Hash
    trace_hash: SHA256Hash
    classification: EvaluationClassification
    summary_metrics: EvaluationSummaryMetricsV1
    completed_at: UTCDateTime

    @property
    def is_promotable(self) -> bool:
        return True


type EvaluationResultV1 = Annotated[
    ExploratoryEvaluationResultV1 | PromotionEvaluationResultV1,
    Field(discriminator="lane"),
]
```

### 4.4 Absolute Non-Upgrade Rule
There is no constructor, helper, API endpoint, or migration function that converts an `ExploratoryEvaluationResultV1` into a `PromotionEvaluationResultV1`.
If an exploratory evaluation run demonstrates promising performance, that result serves solely as justification to invest capital in acquiring promotion-qualified M1e data. Promotion requires an entirely NEW, independent evaluation run executed against the newly qualified dataset with a new run ID, new trace, and fresh validation.

---

## 5. Evaluator Core Boundary

The evaluator core is a pure Python engine with zero network, filesystem, or provider dependencies.

```
+-----------------------------------------------------------------------------+
|                             Drift Domain Layer                              |
|                                                                             |
|  [M1b Universes]   [M1c Corporate Actions]   [M1d Sessions & Observations]  |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                      EvaluationInputBundleV1 (Immutable)                     |
|                                                                             |
|  - Resolved security/listing mappings (M1b)                                 |
|  - Historical universe membership series (M1b)                              |
|  - Sourced corporate action occurrences & terms (M1c)                       |
|  - Realized session calendar & trading hours (M1d)                          |
|  - Source-basis unadjusted observations (open, close, volume) (M1d)         |
|  - Split-normalized decision-role observation views (M1d)                   |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                             Evaluator Engine                                |
|                                                                             |
|  Input: Strategy + InputBundle + Protocol + CostModel + Admission           |
|  Output: TraceLog + EvaluationSummary + ClassifiedResult                    |
+-----------------------------------------------------------------------------+
```

The evaluator core accepts:
1. An executable `RuntimeStrategy` conforming to the pure strategy protocol.
2. A validated `EvaluationInputBundleV1`.
3. A declared `EvaluationProtocolV1`.
4. An explicit `EvaluationCostModelV1`.
5. An admitted `EvaluationAdmissionV1`.

The core never interacts with:
- Raw provider bytes, files, or responses (Alpaca, Databento, algoseek).
- Network sockets or HTTP clients.
- Global mutable state or system clocks.
- Broker accounts, orders, or paper trading endpoints.

---

## 6. Runtime Strategy Protocol and Whole-Share Target Intent

### 6.1 Strategy Provenance Separation
Existing M0 domain models (`StrategyReference`, `StrategyArtifact`) are immutable provenance records storing code hashes, artifact references, and hypothesis links. They remain untouched.

### 6.2 Pure Strategy Protocol
M2 introduces a runtime protocol executed during the post-close decision phase:

```python
class PositionViewV1(FrozenModel):
    """Causal, point-in-time view of an existing portfolio holding."""

    security_id: UUID7
    quantity: int
    cost_basis: Decimal
    average_cost_per_share: Decimal


class StrategyDecisionContextV1(FrozenModel):
    """Causal, point-in-time information set provided to a strategy."""

    session_key: SessionKeyV1
    decision_cutoff: UTCDateTime
    admitted_universe: tuple[UUID7, ...]  # security_ids
    current_holdings: tuple[PositionViewV1, ...]
    current_cash: Decimal
    portfolio_nav: Decimal
    decision_views: Mapping[str, tuple[DerivedObservationViewV1, ...]]


class SecurityTargetPositionV1(FrozenModel):
    """Target position intent emitted for one admitted security."""

    security_id: UUID7
    execution_listing_id: UUID7
    target_quantity: int  # Must be >= 0 (whole shares, long-only)


class StrategyDecisionIntentV1(FrozenModel):
    """Complete portfolio intent emitted by a strategy at a decision cutoff."""

    session_key: SessionKeyV1
    decision_time: UTCDateTime
    targets: tuple[SecurityTargetPositionV1, ...]
    strategy_state_artifact: ArtifactReference | None = None


class RuntimeStrategy(Protocol):
    """Pure strategy interface invoked by the evaluator engine."""

    @property
    def strategy_reference(self) -> StrategyReference: ...

    def decide(
        self, context: StrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1: ...
```

### 6.3 Whole-Share Target Positions and Explicit Omission Rule
Strategies emit target WHOLE-SHARE quantities rather than fractional weights or raw buy/sell orders:
- **No Evaluator Capital Allocation Guessing**: The evaluator does not guess how to round fractional shares or allocate remaining cash. The strategy specifies exact target share counts.
- **Explicit Complete Target Set Rule**:
  Any currently held security that is NOT present in `targets` is treated as an explicit liquidation:
  $$\text{target\_quantity} = 0 \quad (\Delta q = -\text{current\_quantity})$$
  If a strategy wishes to maintain an existing holding, it must explicitly include that security in `targets` with `target_quantity = current_quantity`.
- **Long-Only Validation**: Any target quantity $< 0$ immediately triggers a `REJECTED` evaluation classification.
- **Phase 5 vs. Phase 2 Validation Boundary**:
  - In Phase 5 (Post-Close Decision), the engine validates: targets are whole-share integers, targets are non-negative, and new entries (`target > 0`) belong to `admitted_universe`. Phase 5 does NOT validate cash solvency, because next-session open prices and slippage are strictly future unknowns.
  - In Phase 2 (Open Execution), actual cash solvency is enforced when open prices are materialized.

---

## 7. Provider-Neutral Evaluation Input Bundle

An evaluation run operates on a self-contained, content-addressed bundle of Drift artifacts:

```python
class SessionCalendarEntryV1(FrozenModel):
    """One scheduled or realized regular trading session entry."""

    session_key: SessionKeyV1
    session_date: date
    open_time_utc: UTCDateTime
    close_time_utc: UTCDateTime
    session_scope: Literal["regular"] = "regular"


class UnadjustedSessionObservationV1(FrozenModel):
    """Source-basis unadjusted daily session observation record."""

    security_id: UUID7
    session_key: SessionKeyV1
    open_price: Decimal
    close_price: Decimal
    share_volume: int
    is_halted: bool = False


class EvaluationInputBundleV1(FrozenModel):
    """Complete provider-neutral input data for an evaluation interval."""

    schema_version: Literal["1"] = "1"
    bundle_id: UUID7
    evaluation_interval: TemporalIntervalClaimV1
    source_snapshot_hash: SHA256Hash | None = None
    universe_bundle_hash: SHA256Hash
    economic_context_hash: SHA256Hash
    observation_context_hash: SHA256Hash
    session_context_hash: SHA256Hash
    normalization_policy_hashes: tuple[SHA256Hash, ...]
    security_identities: tuple[SecurityV1, ...]
    listing_identities: tuple[ListingV1, ...]
    session_calendar: tuple[SessionCalendarEntryV1, ...]
    unadjusted_observations: tuple[UnadjustedSessionObservationV1, ...]
    decision_observation_views: tuple[DerivedObservationViewV1, ...]
    corporate_action_occurrences: tuple[CorporateActionTermsVersionV1, ...]
    bundle_hash: SHA256Hash
```

The bundle binds exact M1b universe rules, M1c corporate action occurrences, M1d session schedules, and M1d observations. Raw vendor JSON payloads are strictly prohibited.

---

## 8. Temporal Decision Clock and Session Scheduling

M2 implements a strictly causal, lookahead-free evaluation clock:

```
Session D (Regular Trading: 09:30 - 16:00 ET)
  |
  +-- 16:00 ET: Session D Closes
  |
  +-- Post-Close Cutoff: Session D observations become available
  |
  +-- [PHASE 5: POST_CLOSE_DECISION]
        Strategy receives Session D close information set
        Strategy emits target intent for Session D+1
        NO same-day execution permitted
  |
  v
Session D+1 (Next Eligible Regular Trading Session)
  |
  +-- [PHASE 1: PRE_OPEN_EFFECTS]
  |     Apply splits, dividends, spin-offs effective for Session D+1 open
  |     Adjust staged target quantities for corporate action splits
  |
  +-- [PHASE 2: OPEN_EXECUTION] (09:30 ET)
  |     Evaluate execution deltas: Delta q = staged_target' - current_quantity
  |     Execute Sells first, Buys second at Session D+1 unadjusted OPEN price
  |     Validate available cash solvency
  |
  +-- [PHASE 3: INTRASESSION_EFFECTS]
  |     Process daytime cash settlements (payable_date <= current_date)
  |
  +-- [PHASE 4: CLOSE_MARK] (16:00 ET)
  |     Mark portfolio at Session D+1 unadjusted CLOSE price
  |     Record session NAV and trace
  |
  +-- [PHASE 5: POST_CLOSE_DECISION]
        Strategy receives Session D+1 close information set...
```

### 8.1 Elimination of Same-Bar Lookahead
Executing at session D close based on session D close observations is physically impossible without lookahead. M2 guarantees:
- Decisions made after session D close execute exclusively at session D+1 open.
- Knowledge cutoffs are explicitly tracked: session D observations are sealed before the strategy decision function is evaluated.

### 8.2 Explicit Warmup Schedule and Transition
- Evaluation protocols specify an explicit warmup session count $W$ (e.g. 50 sessions).
- Warmup observations populate strategy indicators and rolling state.
- **Warmup Sessions 1 through $W-1$**: Phase 5 does NOT invoke `strategy.decide()`; no target intents are staged.
- **Warmup Session $W$ Post-Close**: Phase 5 invokes `strategy.decide()` for the first time. Target positions are staged for execution at Session $W+1$ open.
- **Session $W+1$**: The first session where Phase 2 (Open Execution) executes trades and fills.

---

## 9. Universe Admission and Historical Survivorship Rules

### 9.1 Sourced M1b Universe Authority
- Evaluator universe membership is determined session-by-session from M1b historical universe claims.
- `MembershipStatus.INCLUDED` admits the security to the eligible decision universe.
- `MembershipStatus.EXCLUDED` or `MembershipStatus.INDETERMINATE` removes the security from eligibility.
- Indeterminate membership is never treated as eligible.

### 9.2 Liquidations Permitted for Excluded Positions
If a security currently held in the portfolio is removed from the universe (e.g. dropped from an index or becoming `EXCLUDED`), the strategy is permitted to emit `target_quantity = 0` to liquidate the holding. Target quantities with `target_quantity > 0` (new entries or additions) for non-admitted securities are strictly rejected.

### 9.3 Anti-Survivorship Invariant
Today's constituent list (e.g. current S&P 500 or active Alpaca assets) cannot be projected backward as a historical universe. Any run attempting to project current symbols historically without dated interval eligibility fails validation.

### 9.4 Bounded Cohort for Exploratory Development
Because Alpaca does not provide a complete historical survivorship-free index universe, the initial Alpaca exploratory bridge uses a declared, bounded security cohort with individually verified point-in-time identities. Exploratory results must explicitly record this cohort restriction as an acknowledged limitation.

---

## 10. Accounting Basis vs. Decision Data (Unadjusted Sourced Prices)

This distinction is load-bearing across the entire quantitative architecture:

| Domain Layer | Data Basis | Source Authority | Purpose |
|---|---|---|---|
| **Strategy Decision Context** | Split-Normalized / Causal Views | M1d Decision Views | Indicator calculations, moving averages, signal formulation. |
| **Portfolio Accounting** | Source-Basis UNADJUSTED Prices | M1d Unadjusted Observations | Cash movements, fill prices, portfolio close marks, NAV. |
| **Corporate Action Economics** | Explicit Economic Terms & Facts | M1c Occurrences & Settlements | Share ratio adjustments, cash dividend receivables, mergers. |

### 10.1 Double-Counting Prevention
Applying split-adjusted or dividend-adjusted prices in portfolio accounting while simultaneously crediting M1c dividends and adjusting share counts double-counts economic gains.
The M2 accounting kernel strictly uses source-basis unadjusted prices. An evaluation configuration attempting to use split-adjusted or total-return prices for portfolio accounting is rejected at validation.

### 10.2 Causal Split Normalization Anchoring
When split-normalized views are provided to `StrategyDecisionContextV1` at Session $S$, they must be causally anchored to Session $S$ (`anchor_session == session_S`). Normalizing historical bars against a future anchor session (e.g. the end of a multi-year backtest) is strictly prohibited as lookahead leakage.

---

## 11. Portfolio State, Cash Accounting, Positions, and Pending Claims Kernel

### 11.1 Identity-Keyed Positions
Holdings are keyed by permanent `security_id` (UUID7), not mutable tickers or primary listings. Changing tickers, exchange transfers, or CUSIP updates do not alter economic position identity. Fills record the specific `listing_id` and venue through which execution occurred.

### 11.2 Portfolio State Model
```python
class SecurityHoldingV1(FrozenModel):
    """Whole-share holding in one admitted equity security."""

    security_id: UUID7
    quantity: int  # Must be > 0
    cost_basis: Decimal  # Total acquisition cost including fees

    @property
    def average_cost_per_share(self) -> Decimal:
        return self.cost_basis / Decimal(self.quantity)


class PendingCashClaimV1(FrozenModel):
    """Receivable for an earned but uncollected cash distribution."""

    claim_id: SHA256Hash  # Deterministically derived from M1c occurrence
    security_id: UUID7
    action_kind: ActionKind
    entitled_quantity: int
    cash_per_share: Decimal
    total_cash_expected: Decimal
    ex_session: date
    payable_session: date


class PortfolioStateV1(FrozenModel):
    """Complete immutable snapshot of portfolio state after a session mark."""

    session_key: SessionKeyV1
    cash_balance: Decimal  # Must be >= 0
    holdings: tuple[SecurityHoldingV1, ...]
    pending_cash_claims: tuple[PendingCashClaimV1, ...]
    holdings_market_value: Decimal
    pending_claims_value: Decimal
    net_asset_value: Decimal  # cash + holdings_market_value + pending_claims_value
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
```

### 11.3 Deterministic Replay and Claim IDs
To guarantee bitwise replay determinism, `PendingCashClaimV1.claim_id` is NOT generated with random `uuid7()`. It is deterministically derived as:
$$\text{claim\_id} = \text{content\_hash}(\text{security\_id}, \text{action\_kind}, \text{ex\_session}, \text{payable\_session})$$

### 11.4 Cost Basis Relief and Realized PnL Formulas
When whole shares are sold ($\Delta q_{\text{sell}} > 0$):
$$\text{Cost Basis Sold} = \Delta q_{\text{sell}} \times \left(\frac{\text{current\_cost\_basis}}{\text{current\_quantity}}\right)$$
$$\text{Gross Realized PnL} = (\Delta q_{\text{sell}} \times P_{\text{fill}}) - \text{Cost Basis Sold}$$
$$\text{Net Realized PnL} = \text{Gross Realized PnL} - \text{Transaction Costs}$$
The remaining position retains:
$$\text{new\_quantity} = \text{current\_quantity} - \Delta q_{\text{sell}}$$
$$\text{new\_cost\_basis} = \text{current\_cost\_basis} - \text{Cost Basis Sold}$$

### 11.5 Pending Claims / Receivables Architecture
Dividends and distributions cannot be treated as settled cash on their ex-date, nor can they be ignored until paid:
- On the **ex-date** (Pre-Open Phase): A `PendingCashClaimV1` is recorded. The receivable adds to portfolio NAV ($\text{total\_cash} = \text{quantity} \times \text{cash\_per\_share}$). Cash balance does NOT increase yet.
- On the **payable date** (Intrasession Phase): All claims where `current_session.local_date >= claim.payable_session` settle into `cash_balance`. This guarantees claims payable on weekends or holidays settle on the next active trading session.

---

## 12. Corporate Actions as First-Class Accounting Events

M2 processes corporate actions natively from M1c economic facts:

### 12.1 Forward and Reverse Splits
- **Trigger**: M1c `ActionKind.FORWARD_SPLIT` or `ActionKind.REVERSE_SPLIT` effective for session $D+1$.
- **Phase**: Applied during `PRE_OPEN_EFFECTS` before open execution.
- **Holdings Adjustment**:
  $$\text{new\_quantity} = \text{int}\left(\text{current\_quantity} \times \frac{n}{d}\right)$$
  Cost basis remains identical; average cost per share divides by $n/d$.
- **Staged Target Adjustment**: Any pending target position staged for session $D+1$ open is scaled by the same ratio:
  $$\text{staged\_target}' = \text{int}\left(\text{staged\_target} \times \frac{n}{d}\right)$$
  This ensures execution deltas computed in Phase 2 maintain the strategy's intended economic weight.

### 12.2 Cash Dividends (`REGULAR_CASH_DIVIDEND`, `SPECIAL_CASH_DISTRIBUTION`)
- **Ex-Date**: Pre-open phase creates `PendingCashClaimV1`.
- **Payable Date**: Intrasession phase settles receivable into `cash_balance`.

### 12.3 Mergers and Acquisitions
- **Cash Acquisitions (`CASH_ACQUISITION`)**: Entire position converts to cash entitlement at the fixed cash consideration price on the effective session date.
- **Stock Acquisitions (`STOCK_ACQUISITION`)**: Position in target security converts to whole shares of acquirer security according to the exchange ratio.
- **Mixed Acquisitions (`MIXED_ACQUISITION`)**: Simultaneously credits cash entitlement and acquirer share holding.

### 12.4 Spin-offs (`SPINOFF`)
Creates a new `SecurityHoldingV1` in the child security with quantity determined by the distribution ratio once M1b proves child security identity.
- **NAV Invariant**: If closing market prices for both parent and child are observable, portfolio NAV is marked normally. If tax cost-basis allocation percentages are unannounced, child holding cost basis is marked indeterminate; realized PnL upon eventual sale fails closed to `INDETERMINATE`, but daily portfolio NAV remains `COMPLETE`.

### 12.5 Terminations, Delistings, and Bankruptcies
Delisting is NOT zero; bankruptcy is NOT zero. Terminal value requires explicit M1c liquidation terms or realized terminal distributions. If terminal proceeds are unknown, the evaluation outcome becomes `INDETERMINATE`. Zero cannot be fabricated.

---

## 13. Deterministic Fill Model

### 13.1 Next-Open Execution Policy
All target deltas execute at session $D+1$ regular session open.

### 13.2 Execution Sequencing and Cash Solvency
To maximize cash availability and avoid artificial budget rejections:
1. **Delta Calculation**:
   $$\Delta q_i = \text{staged\_target}_i - \text{current\_quantity}_i$$
2. **Sell Orders First**: All liquidations and reductions ($\Delta q_i < 0$) execute first at $P_{\text{sell}} = P_{\text{open}}(1 - \text{slippage})$. Proceeds net of costs are credited to available cash immediately.
3. **Buy Orders Second**: All expansions and entries ($\Delta q_i > 0$) execute second at $P_{\text{buy}} = P_{\text{open}}(1 + \text{slippage})$.
4. **Deterministic Ordering Inside Phases**: Within sell and buy phases, orders execute in canonical order sorted by `security_id` UUID bytes.
5. **Cash Exhaustion Handling**:
   If available cash (after sells) is insufficient to fund all required buy orders:
   - The evaluator rejects the unfunded orders.
   - It logs a `FillRejectionTraceEventV1` with the exact cash shortfall.
   - The evaluation result is classified scientifically as `EvaluationClassification.REJECTED`.
   - The software execution status completes normally as `ExperimentRunStatus.COMPLETED` (scientific rejection is not a software crash).

### 13.3 Missing Open Price Fail-Closed
If $P_{\text{open}}$ is missing, zero, or invalid:
- DO NOT substitute close price.
- DO NOT forward-fill prior open.
- The evaluation fails closed to `INDETERMINATE`.

---

## 14. Versioned Cost and Slippage Model

M2 defines an explicit, content-addressed transaction cost model:

```python
class EvaluationCostModelV1(FrozenModel):
    """Explicit deterministic cost and slippage parameters."""

    schema_version: Literal["1"] = "1"
    model_id: NonBlankStr
    commission_per_share: Decimal  # USD per share (e.g. Decimal("0.005"))
    fixed_fee_per_order: Decimal  # USD per order (e.g. Decimal("1.00"))
    notional_fee_basis_points: Decimal  # Basis points on traded value
    adverse_slippage_basis_points: Decimal  # Basis points applied against trade
    cost_model_hash: SHA256Hash
```

### 14.1 Application of Adverse Slippage
- Buy Fill Price: $P_{\text{fill}} = P_{\text{open}} \times \left(1 + \frac{\text{slippage\_bps}}{10000}\right)$
- Sell Fill Price: $P_{\text{fill}} = P_{\text{open}} \times \left(1 - \frac{\text{slippage\_bps}}{10000}\right)$

### 14.2 Total Transaction Cost
$$\text{Cost} = (\text{shares} \times \text{comm\_per\_share}) + \text{fixed\_fee} + \left(\text{shares} \times P_{\text{open}} \times \frac{\text{fee\_bps}}{10000}\right)$$

Changing costs changes the run hash.

---

## 15. Missingness, Indeterminacy, and Fail-Closed Semantics

M2 preserves the tri-state observation semantics established in M1d:

| Missing Event | Prohibited Behavior | Enforced Evaluator Behavior |
|---|---|---|
| Held security missing close price | Forward-fill from previous close | Mark valuation as `INDETERMINATE`; halt stepping. |
| Intended fill missing open price | Fall back to close; synthesize zero | Mark evaluation as `INDETERMINATE`; halt stepping. |
| Dividend distribution amount unstated | Assume zero; invent estimate | Mark dividend entitlement as `INDETERMINATE`. |
| Security delisted without terms | Mark position value as zero | Mark portfolio terminal NAV as `INDETERMINATE`. |
| Strategy emits negative quantity | Clip to zero silently | Reject strategy intent (`REJECTED`). |
| Strategy attempts to buy beyond cash | Execute partial; allow margin | Log `FillRejectionTraceEventV1`; mark `REJECTED`. |

When a fatal indeterminate event occurs during Phase 2 (open missing) or Phase 4 (close missing for held asset), the engine emits `IndeterminateCauseTraceEventV1`, halts subsequent session processing, and marks the result `classification=INDETERMINATE` with `status=COMPLETED`.

---

## 16. Deterministic Per-Session Phase Ordering

Every trading session $S$ executes exactly five discrete, canonical phases in strict sequence:

```
+-----------------------------------------------------------------------------------+
|                           Canonical Per-Session Phases                            |
+-----------------------------------------------------------------------------------+
| PHASE 1: PRE_OPEN_EFFECTS                                                         |
|   - Apply M1c corporate action share conversions effective for session S open.   |
|   - Adjust staged target positions by split ratios.                               |
|   - Record pending cash dividend claims for actions ex on session S.              |
|   - Update share quantities, cost bases, and pending receivables.                 |
+-----------------------------------------------------------------------------------+
| PHASE 2: OPEN_EXECUTION                                                           |
|   - Retrieve staged target positions.                                             |
|   - Derive deltas: Delta q = staged_target - current_quantity.                    |
|   - Fetch unadjusted session S open prices.                                       |
|   - Execute Sells first (credit cash, deduct costs).                              |
|   - Execute Buys second (validate cash solvency, debit cash, deduct costs).       |
|   - Record all fill events and any cash-shortfall rejection events in trace.      |
+-----------------------------------------------------------------------------------+
| PHASE 3: INTRASESSION_ECONOMIC_EFFECTS                                            |
|   - Settle pending cash claims where payable_session <= current_session.date.     |
|   - Process daytime security distributions or tender completions.                 |
+-----------------------------------------------------------------------------------+
| PHASE 4: CLOSE_MARK                                                               |
|   - Fetch unadjusted session S close prices for all currently held positions.     |
|   - Compute market value of holdings.                                             |
|   - Compute total portfolio Net Asset Value (NAV).                                |
|   - Record SessionMarkEvent in the execution trace.                               |
+-----------------------------------------------------------------------------------+
| PHASE 5: POST_CLOSE_DECISION                                                      |
|   - If current session is >= warmup_count W:                                      |
|     - Construct causal StrategyDecisionContextV1 anchored to session S close.      |
|     - Invoke runtime strategy `decide(context)`.                                  |
|     - Validate emitted targets (long-only, whole shares, universe constraints).   |
|     - Apply complete target set rule (omitted holdings get target = 0).           |
|     - Stage valid targets for Session S+1.                                        |
+-----------------------------------------------------------------------------------+
```

---

## 17. Evaluation Result and Canonical Trace Contracts

### 17.1 Granular Trace Events
The evaluator generates an immutable sequence of typed trace events:
- `SessionStartTraceEventV1`
- `CorporateActionAppliedTraceEventV1`
- `FillTraceEventV1`
- `FillRejectionTraceEventV1`
- `ClaimSettledTraceEventV1`
- `SessionMarkTraceEventV1`
- `StrategyDecisionTraceEventV1`
- `IndeterminateCauseTraceEventV1`

The complete sequence hashes into `trace_hash = content_hash(tuple(trace_events))`.

### 17.2 Scientific Evaluation Classification
- `EvaluationClassification`:
  - `COMPLETE`: All required prices, terms, and session facts materialized; accounting executed fully.
  - `INDETERMINATE`: Missing prices, unquantified corporate actions, or unprovable outcomes halted evaluation.
  - `REJECTED`: Strategy intent violated constraints (negative target, leverage, cash exhaustion).

---

## 18. ExperimentSpecification and ExperimentRun M0 Integration

M2 integrates seamlessly with existing M0 models without modifying persisted schemas:

### 18.1 `ExperimentSpecification` Integration
In `src/drift/domain/experiments.py`:
- `evaluation_protocol: ImmutableJSON`: Serializes `EvaluationProtocolV1.model_dump(mode="python")`.
- `cost_assumptions: ImmutableJSON`: Serializes `EvaluationCostModelV1.model_dump(mode="python")`.
- `parameters: ImmutableJSON`: Serializes strategy parameters.
- `strategy_reference: StrategyReference`: Retains provenance to the strategy artifact.

### 18.2 `ExperimentRun` Integration
- `artifact_references`: Includes references to:
  - `EvaluationTraceArtifact`: The full JSONL trace of evaluation events.
  - `EvaluationResultArtifact`: The typed `ExploratoryEvaluationResultV1` or `PromotionEvaluationResultV1`.
- `metrics: ImmutableJSON`: Contains `EvaluationSummaryMetricsV1.model_dump(mode="python")`.
- `dataset_hash`: Binds `EvaluationInputBundleV1.bundle_hash`.
- `status`: Set to `COMPLETED` on normal execution (including scientific `INDETERMINATE` or `REJECTED`), or `FAILED` on unhandled software exception.

---

## 19. Replay Integrity and Content-Addressed Identity

An evaluation run is uniquely identified by its canonical evaluation hash:

$$\text{RunHash} = \text{content\_hash}(\text{strategy\_ref}, \text{params}, \text{input\_bundle}, \text{protocol}, \text{cost\_model}, \text{admission}, \text{code\_hash}, \text{environment\_hash})$$

Re-executing an evaluation with identical inputs, strategy version, protocol, costs, and software environment must produce bitwise-identical trace events, identical accounting numbers, and an identical result hash.

---

## 20. Exploratory Lane Admission Contracts

Canonical strings for acknowledged Alpaca limitations:
```python
ALPACO_LIMITATION_TRUNCATED_CA = (
    "corporate-action-mutation-replay-truncated-to-approx-72-days"
)
ALPACA_LIMITATION_UNVERSIONED_BARS = (
    "derived-bars-unversioned-without-provider-vintages"
)
ALPACA_LIMITATION_ABSENT_HALTS = "trading-halt-telemetry-absent-from-api"
ALPACA_LIMITATION_BOUNDED_COHORT = "evaluation-restricted-to-declared-bounded-cohort"
```

---

## 21. Promotion Lane Admission and Gatekeeper Verification

An admission gatekeeper function operates outside the pure evaluator core:

```python
def validate_promotion_admission(
    admission: PromotionEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    report: PurposeQualificationReportV1,
) -> None:
    """Verify promotion admission against authentic M1e qualification evidence."""
    if admission.lane != "promotion":
        raise ValueError("admission must belong to promotion lane")
    if bundle.source_snapshot_hash != admission.m1e_snapshot_hash:
        raise ValueError("input bundle snapshot mismatch with promotion admission")
    if admission.m1e_purpose != "historical_decision_input":
        raise ValueError("promotion requires historical_decision_input purpose")
    if report.purpose != "historical_decision_input":
        raise ValueError("qualification report purpose mismatch")
    if not all(res.status == QualificationStatus.PASS for res in report.results):
        raise ValueError(
            "promotion admission requires all qualification dimensions to pass"
        )
```

---

## 22. Alpaca Development Bridge and Acquisition Isolation

The Alpaca development bridge is an operational data preparation utility that executes outside the evaluator core.

### 22.1 Architecture Isolation
- The evaluator core NEVER imports or executes the Alpaca bridge.
- The Alpaca bridge runs as an offline intake script (`scripts/intake_alpaca_exploratory.py`).
- It fetches bounded historical SIP bars and corporate actions via authenticated REST endpoints.
- Acquired bytes are stored in private content-addressed storage outside Git.
- An `AcquisitionReceiptV1` and dataset manifest are generated.
- Sourced records are mapped to standard M1b, M1c, and M1d domain models.
- All mapped datasets are validated using Drift's existing public validators (`DatasetValidationDecisionV2`).
- An `ExploratoryEvaluationAdmissionV1` is minted containing explicit known Alpaca limitations.
- An `EvaluationInputBundleV1` is emitted for the evaluator core.

---

## 23. Security, Credential, and Network Boundaries

1. **Evaluator Network Isolation**: The evaluator core and all standard test suites operate with zero network access.
2. **Credential Hygiene**: Alpaca credentials reside exclusively in `.env` (mode 0600, gitignored). Credentials are used solely by the offline acquisition CLI and never appear in test fixtures, manifests, admission tokens, traces, or logs.
3. **No Financial Risk**: The bridge uses market data read endpoints only. No trading account keys, order submission endpoints, or paper trading execution endpoints are accessed.

---

## 24. Compatibility with M0-M1e Persisted Contracts

M2 introduces zero breaking changes to existing contracts:
- `src/drift/domain/experiments.py`: Preserved completely.
- `src/drift/domain/strategies.py`: Preserved completely.
- `src/drift/domain/securities.py`, `universes.py`, `observations.py`: Consumed without modification.
- SQLite schemas and evidence ledger: Preserved without migration.

---

## 25. Adversarial Acceptance Test Matrix

The M2 implementation must pass the following 28 explicit adversarial acceptance tests:

| Category | Invariant Tested | Attack Scenario / Input | Expected Result |
|---|---|---|---|
| **Causality** | Same-Bar Close Lookahead | Strategy requests execution at session D close using session D close price | Rejected by protocol validation. |
| **Causality** | Post-Cutoff Observation Leakage | Observation with availability timestamp > decision cutoff passed to strategy | Filtered out or triggers fail-closed error. |
| **Causality** | Current Ticker Fallback | Historical lookup uses terminal ticker rather than point-in-time ticker | Rejected by M1b identity resolver. |
| **Causality** | Future Corporate Action Knowledge | Strategy context contains corporate action announced after decision date | Rejected by M1c causal selection query. |
| **Universe** | Survivorship Bias | Current active asset list used as historical universe | Rejected; requires historical universe definition. |
| **Universe** | Indeterminate Eligibility | Security with `MembershipStatus.INDETERMINATE` admitted to trading | Rejected; indeterminate is not eligible. |
| **Universe** | Delisted Security Entry | Strategy attempts new position entry after security delisting date | Rejected; security is not in admitted universe. |
| **Accounting** | Double-Counting Adjustment | Accounting configured with split-adjusted prices while applying M1c splits | Validation rejects adjusted accounting prices. |
| **Accounting** | Premature Dividend Settlement | Dividend cash credited to available cash on ex-date before payable date | Rejected; ex-date creates receivable, not cash. |
| **Accounting** | Vanishing Receivables | NAV marked without including valid pending dividend receivables | Rejected; NAV must reflect earned receivables. |
| **Accounting** | Fabricated Delisting Recovery | Security delists without liquidation terms; accounting assumes zero or recovery | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Unquantified Merger Terms | Merger occurs with unknown consideration terms | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Missing Close Forward-Fill | Held position has missing close price; evaluator forward-fills prior close | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Negative Cash Permitted | Buy execution exceeds available cash balance | Fills rejected; cash balance cannot go negative. |
| **Execution** | Close-for-Open Fallback | Missing open price replaced by prior or current close price | Execution fails closed to `INDETERMINATE`. |
| **Execution** | Negative Target Position | Strategy emits negative whole-share target quantity (short position) | Intent rejected; run classified as `REJECTED`. |
| **Execution** | Fractional Share Quantity | Strategy emits floating-point target quantity (e.g. 10.5 shares) | Intent rejected; whole shares only. |
| **Execution** | Buy-Before-Sell Sequencing | Account has insufficient cash until existing position is liquidated | Sells execute first, freeing cash for buys. |
| **Cost** | Cost Parameter Mutation | Cost model modified from 0 bps to 5 bps without changing run identity | Prohibited; cost hash changes run hash. |
| **Cost** | Favorable Slippage Applied | Strategy claims positive price improvement on market order | Prohibited; slippage is strictly adverse. |
| **Evidence Lanes** | Lane Upgrading | Caller attempts to construct `PromotionEvaluationResultV1` from exploratory run | Type system / constructor prohibits operation. |
| **Evidence Lanes** | Mutable Boolean Override | Caller sets `is_promotable = True` on exploratory result | Prohibited; `is_promotable` is an immutable property. |
| **Evidence Lanes** | Unqualified Promotion Admission | Promotion admission submitted without valid M1e qualification report | Validation fails closed; admission rejected. |
| **Evidence Lanes** | Exploratory Input in Promotion | Promotion run configured with exploratory Alpaca input bundle | Validation rejects bundle; requires M1e snapshot. |
| **Replay** | Strategy Mutation | Strategy code hash altered by 1 byte | Run hash changes; replay mismatch detected. |
| **Replay** | Identical Replay Reproducibility | Exact re-execution of identical specification, bundle, and environment | Bitwise identical trace hash and NAV series. |
| **Provider Boundary** | Raw Vendor Payload Leakage | Raw Alpaca JSON dictionary passed into strategy or evaluator core | Prohibited; core accepts only Drift domain models. |
| **Provider Boundary** | Missing Halt Synthesized | Alpaca missing halt data interpreted as affirmative "trading active" | Prohibited; missing halt remains unknown. |

---

## 26. Explicit Non-Goals

M2 does NOT implement:
- Alpha generation or predictive quantitative models (M3+).
- Statistical scorecards, Sharpe ratios, or drawdown analysis (M5).
- Machine learning, reinforcement learning, or LLM agents (M7+).
- Champion/challenger tournaments or promotion decisions (M10/M11).
- Intraday bars, tick data, or high-frequency order books.
- Short selling, margin, leverage, or stock borrowing mechanics.
- Options, futures, foreign exchange, or fixed income.
- Fractional share accounting or optimization solvers.
- Live trading, broker order submission, or Robinhood integration.

---

## 27. Future Architectural Extension Points

M2 V1 establishes clean extension points without implementing them prematurely:
1. **Intraday Session Expansion**: The `SessionScope` and `SessionKeyV1` models natively support adding extended hours or hourly intervals without altering accounting kernel mechanics.
2. **Shorting and Margin Facilities**: A future margin kernel can introduce `BorrowAgreementV1` and short position accounts beside the long-only kernel.
3. **Multi-Currency Valuations**: Cash balances can expand to `Mapping[CurrencyCode, Decimal]` with explicit causal exchange-rate mark events.
4. **Market Impact Simulation**: `EvaluationCostModelV1` can incorporate quadratic or square-root volume participation impact models in M12 without breaking V1 linear costs.
