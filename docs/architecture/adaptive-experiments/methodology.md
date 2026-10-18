# Adaptive Experiment System: Preregistered Scientific Methodology (Issue #377)

## Status and Governance Boundary

- **Issue Reference**: GitHub Issue #377 (Workstream: Kanuj, reparented from #373 to #391 under ADR 0017).
- **Accountable Feature Owner**: Kanuj.
- **Publisher**: KanujVerma.
- **Document Status**: PROPOSED PREREGISTRATION METHODOLOGY. NOT FROZEN. NOT INDEPENDENTLY ACCEPTED.
- **Preregistration Boundary**: A written methodology design is not automatically a preregistered study. Gate G3 acceptance, formal study preregistration, and parameter freezing are separate governance milestones.
- **Review Boundary**: Independent scientific and platform review required before Gate G3 execution. Krish reviews research/proposal compatibility; Matthew reviews timing, mandate, execution, and accounting reconciliation. Author cannot self-certify scientific validity or acceptance.
- **Operating Rules**: Conforms to repository root AGENTS.md, docs/architecture/workstreams.md, and ADR 0017. Zero Unicode em dashes permitted.

---

## 1. Scope and Scientific Question

The primary objective of the Drift Adaptive Experiment System is to evaluate whether a frozen, bounded artificial intelligence (AI) portfolio selector (Arm B) produces higher net-of-trading-cost portfolio returns than a competent, deterministic, risk-aware comparator (Arm R) when operating under matched investment opportunities, identical historical observations, and identical portfolio risk constraints.

The study evaluates selector decision quality conditional on a fixed, pre-approved strategy menu:
$$\mathcal{S} = \{ B3, B4, B5 \}$$

Both selectors (Arm B and Arm R) operate under identical conditions:
- The same proposed 12-ETF universe (subject to independent qualification).
- The same time-eligible market observations and corporate actions.
- The same completed candidate reference outcomes.
- The same monthly decision checkpoints.
- The same permissible strategy action space (selecting B3, B4, or B5).
- The same execution and trading-cost assumptions.
- The same authoritative platform evaluator.

**Non-Claims**:
- The study measures selector quality conditional on this fixed strategy menu.
- It does NOT measure the unrestricted ability of an LLM to invent, generate, or self-modify investment strategies.
- The experiment does not assume the AI selector is superior to the conventional comparator.

---

## 2. Experimental Arms and Controls

All active evaluated accounts are independently isolated with nominal initial capital of exactly USD 10,000.00 per account. Accounts are never pooled, and capital is never transferred across arms.

### 2.1 Primary Comparison Arms
- **Arm B (Primary Treatment - Adaptive AI Selector)**:
  An autonomous, bounded LLM selector choosing monthly among {B3, B4, B5} using time-eligible context, matured own-arm feedback, and frozen reflection rules. Arm B and Arm R must use the same independently accepted Balanced mandate during scored evaluation. The mandate's numerical parameters are currently provisional and must be frozen before Gate G3. This is a study requirement, not evidence of current approval.
- **Arm R (Primary Benchmark - Conventional Optimizer)**:
  A deterministic, non-LLM risk-aware numerical comparator choosing monthly among {B3, B4, B5} using identical reference history and candidate switching costs. Operates under the identical required Balanced mandate once independently approved.

### 2.2 Control and Reference Arms
- **Arm A (Frozen Reference-Selection Policy)**:
  A frozen, fixed-rule selection policy operating on the corrected platform kernel. Frozen means its selection policy is fixed, not that its underlying holdings never change. (Does not assume or invent a static 60/40 SPY/TLT allocation).
- **Arm C (Ordinary Passive Buy-and-Hold Benchmark)**:
  An ordinary passive buy-and-hold benchmark using an accepted, eligible cohort instrument. (Does not authorize introducing SPY into the primary cohort).
- **Arm C-risk (Risk-Matched Passive Comparator)**:
  A separate risk-matched passive control combining an eligible equity index asset with short-term Treasuries/cash to match the target volatility of the Balanced mandate.
- **Arm D (Cash Control)**:
  A capital preservation baseline holding risk-free cash/Treasury equivalents. Yield, custody/platform fees, and inflation assumptions require explicit policy references. (Does not use an invented moving-average crossover rule).

### 2.3 Additional Reference Evidence
- **Independent B3 Reference Portfolio**: Continuous unswitched execution of Strategy B3.
- **Independent B4 Reference Portfolio**: Continuous unswitched execution of Strategy B4.
- **Independent B5 Reference Portfolio**: Continuous unswitched execution of Strategy B5.
- **R-simple**: A naive momentum comparator selecting the previous six-month return winner.
- **R-ML**: A separate, optional conventional machine-learning model study.

**Boundary Note**: Only Arm B and Arm R form the primary confirmatory comparison. Arms A, C, C-risk, D, R-simple, and R-ML are auxiliary controls, not substitutes for primary Arm R. Control arms are not prerequisites for running the minimal synthetic B/R integration test.

---

## 3. Fixed Candidate Strategies: Exact Semantics

The candidate strategy implementations are frozen in the repository and are not open for redesign.

### 3.1 Strategy B3: Monthly Equal-Weight Rebalance
- **Module**: `src/drift/baselines/b3_monthly_equal_weight_rebalance.py`
- **Class**: `B3MonthlyEqualWeightRebalanceStrategy`
- **Behavior**:
  - Monthly equal-weight rebalancing across admitted securities.
  - Equally allocates current portfolio NAV across all admitted cohort assets.
  - Calculates whole-share target quantities using the existing eligible price and rounding logic.
  - Uses existing strategy references and configuration hashes.
  - Retains existing positions between monthly rebalancing decisions.
- **Qualification**: The existing weekday-based month-end heuristic in code is not proof of exchange-calendar qualification. Stage 1 must use separately qualified session schedules without altering B3's frozen algorithm.

### 3.2 Strategy B4: 12-Minus-1 Momentum
- **Module**: `src/drift/baselines/b4_momentum.py`
- **Class**: `B4MomentumStrategy`
- **Behavior**:
  - 12-minus-1 cross-sectional momentum ranking.
  - Requires a minimum of 253 completed historical trading sessions.
  - Analytical score formula:
    $$\text{Score} = \frac{\text{Close}[t-21]}{\text{Close}[t-252]} - 1$$
  - Uses corporate-action-consistent analytical prices.
  - Ranks cohort assets by descending momentum score.
  - Breaks exact ties by existing `security_id` byte ordering.
  - Selects the top $\lceil n / 2 \rceil$ eligible securities.
  - Targets equal-dollar, whole-share allocations across selected securities.
  - Requires a minimum of two eligible securities to produce valid non-empty targets.
- **Prohibition**: B4 does not include an invented positive absolute-momentum filter.

### 3.3 Strategy B5: Low Volatility
- **Module**: `src/drift/baselines/b5_low_volatility.py`
- **Class**: `B5LowVolatilityStrategy`
- **Behavior**:
  - 60 completed close-to-close returns.
  - Requires a minimum of 61 completed historical trading sessions.
  - Computes exact population return variance:
    $$\sigma^2 = \frac{1}{60} \sum_{i=1}^{60} (r_i - \bar{r})^2$$
  - Ranks cohort assets by ascending return variance.
  - Breaks exact ties by existing `security_id` byte ordering.
  - Selects the bottom $\lceil n / 2 \rceil$ eligible securities.
  - Targets equal-dollar, whole-share allocations across selected securities.
  - Requires a minimum of two eligible securities.

### 3.4 Prohibited Descriptions and Invariants
- **Strictly Prohibited Mappings**:
  - B3 is NOT momentum.
  - B4 is NOT mean reversion.
  - B5 is NOT defensive cash.
  - B5 is NOT volatility targeting.
  - B4 is NOT risk parity.
- **Missing Evidence Invariant**: An empty strategy target resulting from missing history or corporate-action gaps must never be interpreted as an instruction to liquidate the account.

---

## 4. ETF Cohort and Qualification

### 4.1 Proposed 12-ETF Primary Cohort
The owner-approved proposed primary universe consists of exactly 12 liquid ETFs spanning four asset classes:
1. **US Large-Cap Equity**: VOO
2. **US Mid-Cap Equity**: IJH
3. **US Small-Cap Equity**: IJR
4. **US Technology Equity**: QQQ
5. **International Developed Equity**: VEA
6. **International Emerging Markets Equity**: VWO
7. **US Short-Term Treasury Fixed Income**: SHY
8. **US Intermediate-Term Treasury Fixed Income**: IEF
9. **US Long-Term Treasury Fixed Income**: TLT
10. **US Inflation-Protected Fixed Income (TIPS)**: TIP
11. **US Investment Grade Corporate Fixed Income**: LQD
12. **Commodities / Gold**: GLD

**Status**: The 12-ETF cohort is PROPOSED, not qualified. Formal qualification receipts are required prior to Gate G1/G3.

### 4.2 Prespecified Sensitivity: 11-ETF Universe (No-QQQ)
To verify that observed selector performance is not driven solely by tech-heavy idiosyncratic returns, a prespecified sensitivity analysis excludes QQQ, evaluating the remaining 11 assets.

### 4.3 Universe Restrictions and Qualification Rules
- **Prohibited Assets**: SPY, IWM, EFA, EEM, HYG, DBC, VNQ, and unapproved alternative assets must NOT be introduced into the primary cohort.
- **Qualification Requirements**: Every admitted ETF must be independently qualified for:
  1. Actual permanent security identity (CUSIP, ticker, FIGI).
  2. Complete listing and trading availability history.
  3. Venue and Market Identifier Code (MIC) compatibility.
  4. NASDAQ and NYSE Arca calendar handling.
  5. Validated corporate actions, splits, and cash distributions.
  6. Price series completeness across all required lookback windows.
  7. Data rights, licensing, and retention permissions.
  8. Point-in-time availability at historical cutoffs.
  9. Eligibility for all fixed candidate strategy algorithms (B3, B4, B5).
- **Missing Qualification**: If any asset fails qualification, its status is marked `UNAVAILABLE`. Missing qualification does not authorize silently substituting an alternative ETF.
- **Reference Allocation**: B3's pre-rounding asset class weights in the 12-ETF universe are approximately 50.0% equities (6/12), 41.7% bonds (5/12), and 8.3% gold (1/12). This illustrative breakdown does not constitute a portfolio mandate approval.

---

## 5. Warmup, Observation and Scoring Timeline

The experiment timeline consists of three strictly separated chronological phases:

### 5.1 Phase W: Warmup Phase
- **Duration**: Minimum 253 completed, eligible trading sessions.
- **Purpose**: Establishes the historical price series and indicators required for B4 (253 sessions) and B5 (61 sessions).
- **Restriction**: No AI selector performance or investment advantage is scored during Phase W.

### 5.2 Phase O: Observation Phase
- **Duration**: Exactly 126 completed, eligible trading sessions following Phase W.
- **Purpose**: Generates counterfactual B3, B4, and B5 historical returns, builds reference outcome series, and matures risk observations.
- **Restriction**: No AI selector performance or investment advantage is scored during Phase O. Scored accounts B and R do not yet exist during Phase O. Reference portfolios may accumulate synthetic PnL, but these gains are not transferred into B or R.

### 5.3 Phase S: Scored Experiment Phase
- **Initialization**: Fresh, independent USD 10,000.00 accounts for Arm B and Arm R are instantiated AFTER Phase W and Phase O are complete.
- **Primary Starting State**: Both Arm B and Arm R start scored evaluation in Strategy B3.
- **First Switch Opportunity**: The first strategy selection checkpoint occurs only after the first completed scored month.
- **Subsequent Checkpoints**: Strategy selection checkpoints occur monthly thereafter.
- **Scoring Duration**: The actual scoring duration is NOT 126 sessions; it remains an explicit, open decision (DP-M1) requiring formal acceptance before Gate G3 execution.
- **Secondary S15 Starting-State Sensitivity**: A separate sensitivity analysis evaluates Arm B and Arm R selecting their initial strategy at $t_0$ based solely on pre-scored Phase O history. This sensitivity is reported separately and cannot be selected post-hoc based on inspection.

---

## 6. Decision Timing and Information Availability

To guarantee strict causality and prevent lookahead bias, all temporal events are governed by distinct timestamps:

1. **Source Event Time**: When a real-world event occurred.
2. **Source First-Available / Receipt Time**: When external data arrived and was validated.
3. **Reference Outcome Maturity Time**: When candidate reference returns became finalized.
4. **Decision-Context Cutoff**: The strict temporal boundary $T(t_k)$ for session $t_k$.
5. **Model / Request Completion Time**: When LLM inference finishes.
6. **Decision Finalization**: When the selector emits its chosen strategy.
7. **Mandate Approval Time**: When platform risk checks complete.
8. **Execution Eligibility**: When orders become eligible for routing.
9. **Actual Fill Time**: When orders execute on the platform.
10. **Result Availability**: When platform `RESULT` records are finalized.

### 6.1 Source Eligibility at Decision Cutoff
A source is eligible at a decision cutoff if and only if all of the following conditions are satisfied:
1. Its exact version and origin are established.
2. Its availability evidence is accepted.
3. The latest defensible availability time is at or before the decision cutoff.
4. Required transformations and derived observations were available by that cutoff.
5. Its rights and scope permit the intended use.
6. Its evidence is complete enough for the decision.

**Non-Equivalences and Invariants**:
- An unknown availability time or an availability interval straddling the cutoff evaluates to `UNAVAILABLE`.
- A content hash alone does not authenticate origin. A source receipt must not be described as proof of cryptographic origin verification.
- **Execution at Next Eligible Open**: Strategy switches decided after a monthly closing cutoff execute at the NEXT ELIGIBLE MARKET OPEN ($t_k + 1$), never at the observed closing price.
- **No Hardcoded Hours**: Closing times must not be hardcoded to 16:00 EST or opens to 09:30 EST. Actual exchange calendars, holidays, early closes, and venue differences must be respected.
- **Anti-Lookahead Invariant**: No result available after the decision cutoff may enter the decision context or be used to justify an earlier decision.

---

## 7. AI Selector and Deterministic Comparator

### 7.1 Primary Adaptive AI Selector (Arm B)
- **Role**: Single autonomous decision-maker.
- **Inputs**:
  - Time-eligible historical performance of B3, B4, and B5.
  - Approved market observations and indicators.
  - Current isolated portfolio positions and cash balances.
  - Approved Balanced mandate constraints.
  - Projected rebalancing transaction costs.
  - Matured, time-eligible own-arm historical feedback.
  - Frozen, versioned evidence-linked reflections.
- **Outputs**:
  - Selected strategy from {B3, B4, B5}.
  - Explicit `NO_CHANGE`, `ABSTAIN`, or `UNAVAILABLE` states.
  - References to supporting evidence IDs.
  - Structured reasoning comparing the choice against maintaining the incumbent allocation.
- **Frozen Configuration**: Model version, system prompts, permitted tools, context assembly logic, memory-update algorithm, decoding parameters, and output validators must be frozen prior to scored execution. Model weights are not retrained during Stage 1A.

### 7.2 Primary Conventional Comparator (Arm R)
- **Ownership**: Krish owns the deterministic comparator algorithm.
- **Constraints**: Evaluates the identical strategy pool {B3, B4, B5} using identical reference information and decision checkpoints.
- **Proposed Utility Function (DP-R6)**:
  For each candidate strategy $s \in \{ B3, B4, B5 \}$, evaluate over the most recent 126 completed eligible reference sessions:
  $$U_s = G_s - \lambda_v V_s - \lambda_{dd} DD_s - C_s$$
  where:
  - $G_s$: Geometric net reference return over 126 completed eligible reference sessions.
  - $V_s$: Sample periodic return volatility scaled to the 126-session horizon.
  - $\text{MDD}_s = \min(\text{drawdown}_t) \le 0$: Maximum peak-to-trough drawdown across the 126-session reference history.
  - $DD_s = |\text{MDD}_s| = \text{abs}(\text{MDD}_s) \ge 0$: Absolute magnitude of maximum drawdown. Therefore, a larger drawdown magnitude strictly decreases utility when $\lambda_{dd} > 0$, preventing accidentally rewarding worse drawdowns.
  - $C_s$: Estimated switching cost from current holdings to strategy $s$, as a fraction of NAV.
  - $\lambda_v, \lambda_{dd} \ge 0$: Open risk penalty coefficients fitted on development data within bounded search grids and frozen before Gate G3.
- **Selection Logic**:
  1. Filter out candidates with missing history or unfulfilled requirements.
  2. Rank eligible candidates by descending $U_s$.
  3. Break ties by preferring the valid incumbent strategy; otherwise follow fixed order (B3, B4, B5).
  4. If no candidate is eligible, fail closed (`ABSTAIN`).
- **Governance Status**: DP-R6 is a recommended proposed comparator, not an approved algorithm. Its exact formula and parameters require formal owner and Krish review before Gate G3.

---

## 8. Risk and Mandate Policy

### 8.1 Mandate Governance
The primary experiment requires the Balanced portfolio mandate, but its final numerical limits (leverage, asset caps, cash floors) are provisional and not yet accepted.

### 8.2 Primary Incoming Switch Handling
1. The scientific layer verifies that the proposed strategy choice is valid and eligible.
2. Matthew's platform independently evaluates the resulting target portfolio against the mandate.
3. If a proposed switch violates the mandate, Matthew's platform rejects the transition.
4. The account retains its existing portfolio strategy only if the current portfolio remains mandate-compliant.
5. If the current portfolio is also non-compliant, platform containment and remediation rules govern the account.
6. The AI selector cannot select cash as an ad-hoc fourth strategy.

### 8.3 Secondary Policies
- **Minimum Trim Policy**: Deterministic minimal reduction of violating positions, preserving residual cash.
- **Dynamic Volatility / Drawdown Overlay**: Secondary risk overlay rules.
- **Rule**: Primary rejection and secondary adjustments must never be mixed within a single experiment.

---

## 9. Investment and Operating-Cost Accounting

Drift maintains a strict separation between authoritative portfolio accounting and external economic cost attribution.

### 9.1 Authoritative Portfolio Accounting (Matthew)
Matthew produces the sole authoritative portfolio record, including:
- Account identifiers and balances.
- Realized cash, positions, and dividend receipts.
- Order routing, execution fills, and explicit trading costs (commissions, slippage, exchange fees).
- Valuation and net asset value (NAV).
- Reconciled platform `RESULT` evidence.

Trading costs are deducted directly from portfolio cash by Matthew's platform ledger and diminish portfolio NAV.

### 9.2 Derived Scientific Cost-Attribution View (Kanuj)
The scientific layer produces a **derived scientific cost-attribution view**. It consumes:
1. Matthew's authoritative net portfolio account.
2. Krish's authoritative `raw_cost` receipts.
3. A frozen attribution policy.

**Critical Non-Equivalence**: The derived scientific cost-attribution view is NOT a second persisted accounting authority, not an economic ledger, not an external economic ledger, and not a scientific cost ledger. External research and inference expenses are NEVER debited from the portfolio cash balance or trading ledger.

### 9.3 Accounting Definitions and Formulas
- **Net Portfolio Gain**:
  $$\text{Gain}_{\text{portfolio}}(X) = \text{NAV}_T(X) - \text{NAV}_0(X)$$
- **Attributable Operating Cost**:
  $$\text{Cost}_{\text{operating}}(X) = \sum \text{InferenceCost} + \sum \text{DataCost} + \sum \text{ComputeCost}$$
- **Per-Arm Economic Gain**:
  $$\text{Gain}_{\text{economic}}(X) = \text{Gain}_{\text{portfolio}}(X) - \text{Cost}_{\text{operating}}(X)$$
- **Comparative Economic Advantage**:
  $$\Delta_{\text{economic}} = \text{Gain}_{\text{economic}}(B) - \text{Gain}_{\text{economic}}(R)$$
- **Primary Paired Portfolio-Return Difference**:
  $$\Delta_{\text{terminal}} = \left( \frac{\text{NAV}_T(B)}{\text{NAV}_0(B)} - 1 \right) - \left( \frac{\text{NAV}_T(R)}{\text{NAV}_0(R)} - 1 \right)$$

**Accounting Invariants**:
- Portfolio return (dimensionless ratio) and economic gain (USD) must be reported with explicit units.
- Trading transaction costs are embedded in NAV and must never be deducted twice.
- Unknown operating costs are not treated as zero; missing costs result in `MISSING_COST` for economic gain without invalidating verified portfolio NAV.
- Shared research costs are allocated per a frozen campaign rule, reconciling exactly once.

---

## 10. Primary Outcome and Uncertainty

### 10.1 Primary Endpoint
The primary confirmatory endpoint is the paired terminal net portfolio return difference:
$$\Delta_{\text{terminal}} = R_{\text{net}}(B) - R_{\text{net}}(R)$$

### 10.2 Secondary Diagnostic Metrics
Calculated strictly per Metric Contract #382:
- Periodic paired return differences: $d_t = r_t(B) - r_t(R)$.
- Maximum drawdown (MDD) and drawdown difference.
- Realized return volatility.
- Periodic excess-return Sharpe ratio (evaluated over excess periodic returns, never geometric return divided by volatility; evaluates to `UNDEFINED` if variance is zero).
- Sortino ratio and downside deviation.
- Portfolio turnover.
- Total operating and economic costs.

### 10.3 Rejection of Naive i.i.d. Assumptions
Daily return series resulting from monthly strategy selections exhibit autocorrelation, volatility clustering, and shared factor exposure.
- Daily observations must NOT be treated as independent, identically distributed draws.
- Degrees of freedom cannot be equated to the count of daily trading sessions ($N$).
- A single paired terminal return difference $\Delta_{\text{terminal}}$ is a descriptive point estimate; it does not constitute statistical proof of superiority on its own.

### 10.4 Proposed Uncertainty Protocol (DP-M1)
- **Primary Resampling**: Paired dependence-preserving stationary block bootstrap (Politis & Romano, 1994) with data-driven block length selection.
- **Complementary Diagnostic**: Heteroskedasticity and Autocorrelation Consistent (HAC) Newey-West standard errors where asymptotic assumptions are defensible.
- **Open Decisions (DP-M1)**: Resampling algorithm, block length calibration, test statistic, number of bootstrap samples, nominal alpha, confidence intervals, sample duration, and materiality return hurdle must be formally approved before Gate G3.

---

## 11. Experimental Comparison Matrix

The experiment specifies eight distinct study designs:

| Study ID | Study Name | Primary Objective | Key Controls and Invariants |
|---|---|---|---|
| **Study 1** | Stage 1A Primary B vs. R | Evaluate incremental selector quality on fixed {B3, B4, B5}. | Matched information, identical Balanced mandate, next-open execution. |
| **Study 2** | S15 Starting-State Sensitivity | Test whether pre-scored initial selection adds value. | B and R select initial strategy using Phase O history; reported separately. |
| **Study 3** | Matched Research Search | Compare search efficiency across candidate generators. | Count ALL attempted proposals, including failures, duplicates, and retries. |
| **Study 4** | Flexible Economic Budgets | Evaluate performance under explicit compute/spend caps. | Fully track inference, tool, token, and compute expenses in derived attribution view. |
| **Study 5** | News-Content Ablation | Isolate the incremental information value of news. | Matched review timing; news text present vs. news text absent. |
| **Study 6** | News-Trigger-Timing Ablation | Measure the value of asynchronous review timing. | Event-driven triggers vs. fixed-calendar reviews; never conflate with content. |
| **Study 7** | One Agent vs. Three Agents | Evaluate multi-agent committee scaling. | Matched model capability and action space; aggregate all tokens and compute. |
| **Study 8** | Robustness Sensitivities | Test sensitivity to universe, risk, and comparator choices. | 11-ETF no-QQQ, R-simple, R-ML, minimum trim, dynamic risk overlay. |

Secondary study findings never retroactively replace the preregistered primary comparison. Multi-agent orchestration (10 agents) and Milestone M9 remain conditional.

---

## 12. Holdout and Learning Discipline

### 12.1 Historical Partitions
- **2021-2023**: Development and exploratory training partition.
- **2024**: Retrospective validation partition.
- **2025**: Potential historical holdout partition, strictly conditional on an exposure audit.

### 12.2 Holdout Integrity and Contamination
- 2021-2023 development and 2024 validation periods must not be portrayed as prospective confirmation.
- 2025 data is historical, not prospective.
- If prompt tuning, model pretraining, or analyst inspection touched 2025 data, it is classified as `CONTAMINATED_HOLDOUT` and cannot be relabeled pristine.
- True prospective evidence requires an untouched, forward broker-free shadow observation phase (Gate G5).

### 12.3 Adaptive Learning Protocol (DP-R8)
- System prompts, model versions, and memory-update logic remain frozen.
- Only strictly time-eligible, matured own-arm feedback is admitted to memory.
- Cross-arm comparative performance and leaderboards are sealed during scored execution.
- Data exposed during interactive development is retired from confirmatory holdout evaluation.

---

## 13. Outcome Classifications and Stopping

### 13.1 Five Scientific Reporting Categories
**Proposed policy for independent DP-M1 review, not an accepted classifier.** Before Gate G3, independently accept and freeze the required evidence, decision predicates and precedence below. No numerical threshold or scientific acceptance follows from this proposal.

At the frozen reporting time, apply the following ordered decision table. The first matching row supplies exactly one of the five scientific reporting states; retain all other validity, missingness and termination reasons alongside it.

| Priority | Condition, after excluding all earlier rows | Proposed Scientific State |
|---|---|---|
| 1 | A scientific validity breach is established, including lookahead, causal timing breach, corrupted trial preimages, or mandate, leverage or risk violation. | `INVALID` |
| 2 | Required source, account, causal or cost evidence needed to establish a valid paired portfolio/economic outcome is absent or unverified. | `UNAVAILABLE` |
| 3 | Required outcome evidence is complete and valid, and $\Delta_{\text{terminal}} \le 0$ or $\Delta_{\text{economic}} \le 0$. | `UNSUCCESSFUL` |
| 4 | Required outcome evidence is complete and valid; both differences are positive; all frozen significance, materiality, evidence/power, minimum scored/prospective evidence, risk-comparability and independent scientific replication/acceptance conditions are satisfied. | `SUCCESS` |
| 5 | Required outcome evidence is complete and valid; both differences are positive; at least one row 4 confirmation condition is not met or remains pending, including independent replication. | `PROMISING_BUT_INCONCLUSIVE` |

**Proposed Policy Choices and Classification Rules**:
- This completeness-first ordering preserves known invalidity ahead of missingness and places complete nonpositive portfolio or economic evidence ahead of an inconclusive positive point estimate. DP-M1 reviewers must accept or revise these choices before freezing; they are not permanent defaults.
- Missing research cost produces `MISSING_COST` for the derived economic view without invalidating verified portfolio NAV. Under proposed row 2, report that NAV and any known nonpositive portfolio result with its limitation while the overall scientific category remains `UNAVAILABLE`.
- Pending confirmation or independent replication is distinct from missing required outcome evidence: complete, valid positive point estimates remain `PROMISING_BUT_INCONCLUSIVE` until every frozen success condition is met.
- DP-M1 must define the required evidence set, valid predicates, treatment of pending confirmation and precommitted reporting time so these rows remain exhaustive and mutually exclusive. Until that accepted Gate G3 freeze, do not assign automatic scientific classifications from observed returns.

### 13.2 Operational Termination Separation
Operational termination is recorded as an independent execution attribute:
`termination_reason = SAFETY_TERMINATED`

A safety termination is NOT a competing scientific outcome category. It can coexist with partial, unavailable, or invalid scientific evidence. Automatic scientific failure must not be claimed merely because an operational safety control activated.

---

## 14. Open Decisions Required Before Scoring

The following items are designated Decision Packets and must be formally resolved and approved prior to Gate G3 execution:
- **DP-R6**: Mathematical formulation, risk penalty weights ($\lambda_v, \lambda_{dd}$), and fitting procedure for conventional comparator R.
- **DP-M1**: Confirmatory uncertainty estimation parameters (bootstrap block length calibration, nominal alpha, confidence level, test statistic, number of resamples and materiality threshold), plus the following required preregistration decisions:
  - Unit of analysis and paired sampling design; dependence across dates, overlapping windows and shared market histories; stochastic-run/replication count, seed assignment and model-sampling policy. Freeze what qualifies as independent scientific replication and its acceptance evidence.
  - Replaying captured responses checks reproducibility; seed reuse alone does not establish deterministic model output. Neither creates additional independent investment observations or scientific replicates. Retain actual requests/responses and seed references; do not inflate the effective sample size by replaying them.
  - Minimum scored and prospective duration/evidence, evidence/power requirements, scheduled reporting/review looks, permissible scientific stopping, extension and repeated-look treatment. Freeze these before scored outcomes; operational safety termination remains the separate attribute in Section 13.2.
  - Declared primary/secondary/exploratory comparison families, all-attempt/variant accounting and multiplicity treatment, including how exploratory selection requires fresh validation.
  - Section 13.1's proposed outcome precedence, required evidence set and confirmation predicates, including significance, materiality, risk comparability and pending independent replication. No values or policy choices become defaults before independent acceptance and Gate G3 freeze.
- **DP-R8**: Memory update rules, reflection schemas, and own-arm feedback policies.
- **Mandate Limits**: Final numerical caps for the Balanced portfolio mandate.
- **Cohort Qualification**: Formal qualification receipts for the 12 primary ETFs.

---

## 15. Worked Synthetic Verification Cases

### Case M01: All-Attempt Spending Denominator
- **Scenario**: Arm B generates 200 candidate proposals to achieve 20 valid accepted allocations. Arm R generates 20 candidate proposals to achieve 20 valid allocations.
- **Expected Outcome**:
  - Proposal yields: Arm B = 20/200 (10.0%), Arm R = 20/20 (100.0%).
  - Total research cost for Arm B must account for all 200 attempts, not just the 20 accepted allocations.
- **Rationale**: Prevents hiding candidate search costs by reporting only winning allocations.

### Case M02: Late News Arrival and Anti-Lookahead
- **Scenario**: Decision-context cutoff is 12:00 UTC. A news event receipt is timestamped 12:10 UTC.
- **Expected Outcome**: The news item must be excluded from the 12:00 UTC context. If included, the run is flagged as `INVALID` due to lookahead bias.
- **Rationale**: Enforces causal temporal separation.

### Case M03: Investment vs. Operating Cost Accounting
- **Scenario**: Initial capital = $10,000.00 USD. Gross investment gain = +$120.00 USD. Realized trading costs = $160.00 USD. LLM inference cost = $80.00 USD.
- **Expected Outcome**:
  - Net portfolio gain = $120.00 - $160.00 = -$40.00 USD.
  - Terminal net NAV = $9,960.00 USD.
  - Total economic gain = -$40.00 - $80.00 = -$120.00 USD.
  - Trading costs ($160.00) are embedded in NAV; inference cost ($80.00) is tracked in the derived scientific cost-attribution view, not debited from portfolio cash.
- **Rationale**: Prevents double-counting trading friction and preserves cash accounting integrity.

### Case M04: Zero-Volatility Cash Control Sharpe Ratio
- **Scenario**: Cash control account holds risk-free Treasury bills with constant return; risk-free benchmark rate matches exactly. Excess return variance is 0.0.
- **Expected Outcome**: Sharpe ratio evaluates to `UNDEFINED`, with reason `ZERO_RETURN_VARIANCE`. It is never mapped to 0.0 or infinity.
- **Rationale**: Enforces mathematical precision per Metric Contract #382.

### Case M05: Contaminated Holdout Identification
- **Scenario**: System prompts and selector thresholds are tuned iteratively against 2025 market returns, after which the period is designated as the "2025 Holdout".
- **Expected Outcome**: Data audit flags the dataset as `CONTAMINATED_HOLDOUT`. Prospective out-of-sample claims are revoked.
- **Rationale**: Protects empirical integrity against data snooping.

### Case M06: Serially Correlated Daily Returns
- **Scenario**: Scored phase observes 126 daily returns from 6 monthly strategy allocations. An analyst runs an ordinary t-test assuming 125 degrees of freedom.
- **Expected Outcome**: The analysis is rejected as `INVALID_INFERENCE`. Uncertainty must be estimated via block bootstrap or HAC standard errors.
- **Rationale**: Prevents inflating statistical confidence through correlated observations.

### Case M07: Unequal Multi-Agent Resource Budgets
- **Scenario**: A single-agent selector uses 10,000 tokens ($1.00 USD) and achieves a 2.0% return. A three-agent committee uses 30,000 tokens ($3.00 USD) and achieves a 2.2% return.
- **Expected Outcome**: The report must highlight that the committee consumed 3x the budget. It cannot claim algorithmic efficiency without budget matching.
- **Rationale**: Isolates model capability from compute scaling.

### Case M08: Missing Eligibility and Incumbent Retention
- **Scenario**: Strategy B4 has only 200 completed sessions (fewer than the required 253 sessions).
- **Expected Outcome**:
  - Strategy B4 evaluates to `UNAVAILABLE`.
  - The account retains the incumbent strategy only if its current holdings, account state, source evidence, mandate, and permissions remain valid.
  - If the existing account state is invalid or non-compliant, the system must fail closed under the platform's accepted containment rules.
  - The system must never fabricate liquidation or assume that holding an invalid account state is safe.
- **Rationale**: Prevents accidental liquidation while strictly enforcing platform containment safety.

---

## 16. Dependencies, Gates and Acceptance

The experimental methodology is bound to Drift's sequential release gates exactly as specified in PR #419:
- **Gate G0 (Governed Documentation)**: ADR 0017 and workstream governance independently accepted and merged.
- **Gate G1 (Source and Strategy Eligibility)**: 12-ETF cohort qualified and baseline strategy algorithms (B3, B4, B5) certified.
- **Gate G2 (Accepted Contracts & Deterministic Integration)**: Upstream producer contracts (#375, #376, #379, #380) and scientific contracts (#392, #382, #383) merged AND contract-bound deterministic integration evidence demonstrated. (The #383 design document alone does not prove that integration has been implemented or tested).
- **Gate G3 (Preregistered Scored-Study Freeze)**: Open Decision Packets (DP-R6, DP-M1, DP-R8) frozen before unblinding scored data.
- **Gate G4 (Qualified Historical Evidence)**: Execution across authorized, qualified historical evidence (2021-2023 development and 2024 validation partitions). Development and validation periods must not be portrayed as prospective confirmation.
- **Gate G5 (Broker-Free Prospective Shadow Observations)**: Live prospective shadow observation without broker connectivity.
- **Gate G6 (Operational Production Authority)**: Completely separate operational gate requiring explicit multi-owner authorization.

**Independent Sign-Off**: All scientific methodology specifications must be reviewed and accepted by research owner Krish and platform owner Matthew. Authors cannot self-certify acceptance.
