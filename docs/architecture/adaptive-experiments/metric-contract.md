# Benchmark Metric Definitions and Measurement Arithmetic Contract

## Start here: authority before action

This is the canonical scientific specification for **BENCHMARK METRICS AND ARITHMETIC**,
produced under [#382](https://github.com/KanujVerma/drift/issues/382) to define reproducible,
mathematically rigorous, and auditable financial metrics for Drift's adaptive experiments.

**This is a contract specification proposal. It implements no runtime code,
persisted database schemas, or autonomous trading permissions.** The proposed wire
profile is `drift-metrics/1-draft`. Implementation of these formulas into runtime
scorecards belongs to future implementation issues under the scientific workstream.

A fresh Antigravity agent or human reviewer should note:

1. Read [AGENTS.md](../../../AGENTS.md), [decisions.md](decisions.md) (D01-D17),
   [design.md](design.md), [workstreams.md](../workstreams.md),
   [requirements-crosswalk.md](requirements-crosswalk.md),
   [stage1-decisions.md](stage1-decisions.md) (S01-S38), and
   [stage1-roadmap.md](stage1-roadmap.md).
2. **Current implementation audit:** The existing implementation in
   `src/drift/scorecards/performance.py` contains severe mathematical defects:
   - It divides geometric annualized return by sample volatility and mislabels the
     result as "Sharpe ratio".
   - It silently returns `ZERO` for mathematically undefined ratios (e.g., zero volatility).
   - It lacks explicit handling for irregular spacing, external flows, and missing intervals.
3. **Four explicit analytical states:** To eliminate silent zeroes, every metric calculation
   evaluates to one of four mutually exclusive states:
   - `KNOWN`: Valid mathematical result computed over complete verified data.
   - `UNDEFINED`: Mathematically indeterminate (e.g., division by zero standard deviation).
   - `UNAVAILABLE`: Required inputs missing, unverified, or temporally misaligned.
   - `INVALID`: Contradictory, corrupt, or nonpositive initial capital inputs.
4. **Single authoritative account ledger:** Metric calculations consume Matthew's
   authoritative platform ledger (`RESULT`, cash, positions, and net NAV).
   The scientific layer performs **scientific cost attribution** by joining Krish's
   spending receipts without double-counting trading friction.
5. **No self-certification:** Per ADR 0017, the scientific author cannot self-certify
   their own metric formulas or verification evidence. Independent scientific review
   is mandatory before benchmark scoring.

---

## 1. Scope, Non-Goals, and Ownership

### 1.1 Scope and Objective
This contract defines the exact mathematical formulas, data requirements, annualization
conventions, and failure states for:
- Periodic returns ($r_t$) and terminal cumulative return ($R_{\text{terminal}}$).
- Geometric annualized return ($R_{\text{annualized}}$).
- Periodic excess returns ($e_t$) and sample excess-return volatility ($\sigma_e$).
- True periodic excess-return Sharpe ratio ($\text{Sharpe}_{\text{annualized}}$).
- Peak-to-trough drawdown profiles and maximum drawdown ($\text{MDD}$).
- Target-adjusted downside semi-deviation and Sortino ratio.
- Calmar ratio.
- Three-tier financial reporting (Gross, Net NAV, Total Economic Advantage).
- Twelve hand-checkable golden arithmetic verification cases.

### 1.2 Non-Goals
- **No Runtime Code Modification:** This contract does not edit `src/drift/domain/scorecards.py`,
  `src/drift/scorecards/performance.py`, or persisted scorecard schemas under #382.
- **No Statistical Promotion:** Computing a metric does not grant promotion authority.
  Defects in M11 promotion criteria remain tracked separately in GitHub issue #360.
- **No Invented Numerical Thresholds:** Material statistical hurdles ($\delta^*$),
  significance levels ($\alpha$), and risk caps remain open Decision Packets.

---

## 2. Core Return and Risk Metric Definitions

All return calculations require verified, consecutive account valuation marks
produced by Matthew's platform ledger. Returns are expressed as decimal fractions
(e.g., `+0.10` for +10%), never percentages.

---

### B1. Periodic Returns ($r_t$)

For consecutive trading sessions $t-1$ and $t$ with verified net asset values $\text{NAV}_{t-1}$
and $\text{NAV}_t$:

$$r_t = \frac{\text{NAV}_t}{\text{NAV}_{t-1}} - 1$$

#### Preconditions and Invariants
1. **Valuation Timestamps:** Valuation marks must align to official session closing marks
   on a declared exchange calendar (e.g., `XNYS` / `ARCX`).
2. **Currency and Basis:** Both marks must share identical base currency (`USD`) and net
   cost basis (after execution commissions and slippage).
3. **External Cash Flows:** The primary adaptive protocol evaluates closed books with
   no intermediate external cash deposits or withdrawals ($C_t = 0$). If an external flow
   occurs without an accepted time-weighted adjustment receipt, the affected interval
   is classified as `UNAVAILABLE`.
4. **No Silent Zeroes:** A missing valuation mark cannot be imputed as $r_t = 0.0$.
   Missing marks yield `UNAVAILABLE` for that interval and invalidate dependent path statistics.

---

### B2. Terminal Return ($R_{\text{terminal}}$)

The cumulative return over the complete evaluation horizon $t = 0$ to $t = T$:

$$R_{\text{terminal}} = \frac{\text{NAV}_T}{\text{NAV}_0} - 1$$

#### Relation to Periodic Returns
For a complete, consecutive series with zero external flows, terminal return compounds:

$$1 + R_{\text{terminal}} = \prod_{t=1}^T (1 + r_t)$$

#### Invariants
- Terminal return is **distinct** from the arithmetic mean ($\frac{1}{T}\sum r_t$) or
  arithmetic sum ($\sum r_t$) of periodic returns.
- It compounds discrete trading friction, spread crossing, and cash drag at each rebalance.

---

### B3. Geometric Annualized Return ($R_{\text{annualized}}$)

For an equally spaced series of $n$ completed trading sessions with declared annualization
frequency $K$ (e.g., $K = 252$ for daily sessions, $K = 12$ for monthly checkpoints):

$$R_{\text{annualized}} = (1 + R_{\text{terminal}})^{K / n} - 1$$

#### Invariants
1. **Not the Sharpe Numerator:** $R_{\text{annualized}}$ is a compound geometric growth rate.
   It must **never** be used as the numerator of the Sharpe ratio.
2. **Spacing Invariance:** Annualization requires complete, equally spaced observation intervals.
   Irregularly spaced observations cannot be annualized without a declared calendar-day convention.
3. **Domain Bound:** If $1 + R_{\text{terminal}} \le 0$ (total loss of capital),
   $R_{\text{annualized}} = -1.0$ if $R_{\text{terminal}} = -1.0$, or `UNDEFINED` if negative.

---

### B4. Periodic Excess Returns ($e_t$)

For each valid periodic return $r_t$ and matching period risk-free rate $rf_t$:

$$e_t = r_t - rf_t$$

#### Invariants
1. **Basis Alignment:** $rf_t$ must reflect the risk-free return over the exact period
   between $t-1$ and $t$. An annualized Treasury yield must be de-annualized to the session
   basis before subtraction.
2. **Missing Risk-Free Data:** An unavailable risk-free series cannot be assumed to be zero.
   If $rf_t$ is unverified, excess returns are `UNAVAILABLE`.
3. **Explicit Fixtures:** For synthetic arithmetic tests, an explicit fixture policy of
   $rf_t = 0.0$ is permitted when explicitly declared.

---

### B5. Sample Excess-Return Volatility ($\sigma_e$)

For $n \ge 2$ valid, consecutive periodic excess return observations:

$$\bar{e} = \frac{1}{n} \sum_{t=1}^n e_t$$

$$s_e^2 = \frac{1}{n - 1} \sum_{t=1}^n (e_t - \bar{e})^2$$

$$\text{sample\_std}(e) = \sqrt{s_e^2}$$

$$\sigma_{e, \text{annualized}} = \text{sample\_std}(e) \times \sqrt{K}$$

#### Invariants
- Sample variance uses degrees of freedom $n - 1$.
- Total portfolio return volatility ($\sigma_r$) must be reported separately from
  excess-return volatility ($\sigma_e$) whenever $rf_t$ is non-constant.

---

### B6. True Periodic Excess-Return Sharpe Ratio

The Sharpe ratio is defined strictly on periodic excess returns:

$$\text{Sharpe}_{\text{annualized}} = \frac{\bar{e}}{\text{sample\_std}(e)} \times \sqrt{K} = \frac{\frac{1}{n}\sum_{t=1}^n (r_t - rf_t)}{\sqrt{\frac{1}{n-1}\sum_{t=1}^n (e_t - \bar{e})^2}} \times \sqrt{K}$$

#### Preconditions for Calculation
The Sharpe ratio is computed **only** when all of the following hold:
1. Complete, verified return observations exist with $n \ge 2$.
2. Matching period risk-free returns $rf_t$ are verified.
3. Observation spacing matches declared frequency $K$.
4. Sample standard deviation is strictly positive: $\text{sample\_std}(e) > 0$.

#### Failure States and Invariants
- **Zero Volatility:** If $\text{sample\_std}(e) = 0$ (e.g., constant return or cash account
  matching risk-free rate), Sharpe is **`UNDEFINED`** (division $0/0$ or $x/0$).
  It must **never** be replaced with $0.0$ or $\pm\infty$.
- **Short Series:** If $n < 2$, Sharpe is **`UNAVAILABLE`** (`INSUFFICIENT_OBSERVATIONS`).
- **Defect in Legacy Implementation:** The formula in `performance.py` ($R_{\text{annualized}} / \sigma$)
  is mathematically defective and must not be used in adaptive experiment scorecards.

---

### B7. Drawdown Profile and Maximum Drawdown ($\text{MDD}$)

Drawdown measures peak-to-trough equity decline relative to historical peak valuation,
including initial capital $\text{NAV}_0$:

$$\text{peak}_0 = \text{NAV}_0$$

$$\text{peak}_t = \max(\text{peak}_{t-1}, \text{NAV}_t) = \max_{s \in [0, t]} \text{NAV}_s$$

$$\text{drawdown}_t = \frac{\text{NAV}_t}{\text{peak}_t} - 1$$

$$\text{MDD} = \min_{t \in [0, T]} \text{drawdown}_t$$

#### Trajectory Metrics
- **Current Drawdown:** $\text{drawdown}_T = \frac{\text{NAV}_T}{\text{peak}_T} - 1$.
- **Peak-to-Trough Duration:** Number of sessions from the peak preceding MDD to the MDD trough.
- **Recovery Duration:** Number of sessions from the MDD trough until NAV reaches or exceeds previous peak.
- **Unrecovered Status:** If $\text{NAV}_T < \text{peak}_T$, the drawdown is marked `UNRECOVERED`.

#### Invariants
- Drawdown is non-positive: $\text{drawdown}_t \le 0.0$.
- Initial capital $\text{NAV}_0$ must be included in the high-water mark history.
- Missing valuation sessions cannot be treated as zero drawdown; missing marks yield `UNAVAILABLE`.

---

### B8. Target-Adjusted Downside Deviation and Sortino Ratio

Downside deviation measures semi-variance below a declared minimum acceptable return ($MAR_t$),
typically set to the period risk-free rate $rf_t$ or zero:

$$\text{shortfall}_t = \min(r_t - MAR_t, 0.0)$$

$$\text{downside\_variance} = \frac{1}{n} \sum_{t=1}^n (\text{shortfall}_t)^2$$

$$\text{downside\_std} = \sqrt{\text{downside\_variance}}$$

$$\text{annualized\_downside\_std} = \text{downside\_std} \times \sqrt{K}$$

$$\text{Sortino}_{\text{annualized}} = \frac{\frac{1}{n}\sum_{t=1}^n (r_t - MAR_t)}{\text{downside\_std}} \times \sqrt{K}$$

#### Invariants
1. **Numerator/Denominator Consistency:** The numerator is periodic mean excess return over $MAR$.
   It must not mix geometric annualized return with periodic downside deviation.
2. **Zero Downside Deviation:** If all returns meet or exceed $MAR$, $\text{downside\_std} = 0.0$.
   The Sortino ratio is **`UNDEFINED`**, never $0.0$.

---

### B9. Calmar Ratio

Calmar ratio measures annualized return relative to maximum drawdown:

$$\text{Calmar} = \frac{R_{\text{annualized}}}{|\text{MDD}|}$$

#### Invariants
1. Requires a complete, verified evaluation horizon (e.g., minimum 36 months in conventional practice;
   minimum precommitted scored window for Stage 1).
2. If $|\text{MDD}| = 0.0$ (monotonically non-decreasing NAV), Calmar is **`UNDEFINED`**, never $0.0$.
3. If $R_{\text{annualized}}$ or $\text{MDD}$ is `UNAVAILABLE`, Calmar is `UNAVAILABLE`.

---

## 3. Financial Reporting Tiers and Cost Attribution

The scientific layer defines three separately labeled reporting views to prevent
confounding trading friction with operational research expenses.

```
+-----------------------------------------------------------------------------+
| View 1: Gross Investment Performance                                        |
| - Pre-trading-cost performance (reported only where explicitly supplied).   |
+--------------------------------------+--------------------------------------+
                                       | Deduct execution commissions,
                                       | spread crossing, and slippage
                                       v
+-----------------------------------------------------------------------------+
| View 2: Net-of-Trading Portfolio Performance (NAV)                          |
| - Authoritative account truth from Matthew's single platform ledger.        |
| - Net Terminal Return: R_net = (NAV_T - NAV_0) / NAV_0                      |
+--------------------------------------+--------------------------------------+
                                       | Deduct attributed research, token,
                                       | and operational inference expenses
                                       v
+-----------------------------------------------------------------------------+
| View 3: Total System Economic Results                                       |
| - Net economic value after attributing operational research expenses.       |
| - Per-Arm Economic Gain = (NAV_T - NAV_0) - Operating_Costs                 |
| - Comparative Economic Advantage = Economic_Gain(B) - Economic_Gain(R)      |
+-----------------------------------------------------------------------------+
```

### Invariants
1. **No Competing Ledger:** Operating expenses are never debited from trading cash in
   Matthew's portfolio ledger.
2. **No Double Deduction:** Trading transaction costs are already reflected in
   Matthew's net portfolio NAV; they must **never** be subtracted a second time.
3. **Gross Return Non-Reconstructibility:** Gross returns cannot be assumed reconstructible
   from net NAV alone. View 1 is reported only when Matthew's platform explicitly provides
   itemized transaction cost logs.
4. **Decoupled Completeness:** Missing research cost receipts make View 3 `UNAVAILABLE`,
   while View 2 (portfolio NAV return) remains fully verified and reportable.

---

## 4. Analytical Metric States

Every computed metric must evaluate to an explicit analytical state object:

```json
{
  "metric_name": "sharpe_ratio",
  "state": "KNOWN",
  "value_decimal": "1.2458",
  "reason_code": null,
  "evidence_references": ["RESULT-REF-001", "RF-REF-001"]
}
```

### State Definitions
- `KNOWN`: Valid mathematical value computed over complete verified inputs.
- `UNDEFINED`: Mathematically indeterminate (e.g., zero volatility, zero MDD).
  Includes reason codes: `ZERO_SAMPLE_VARIANCE`, `ZERO_DOWNSIDE_DEVIATION`, `ZERO_MAXIMUM_DRAWDOWN`.
- `UNAVAILABLE`: Input data missing or incomplete.
  Includes reason codes: `MISSING_VALUATION_MARK`, `MISSING_RISK_FREE_SERIES`, `INSUFFICIENT_OBSERVATIONS`.
- `INVALID`: Contradictory or nonpositive inputs.
  Includes reason codes: `NONPOSITIVE_STARTING_NAV`, `TEMPORAL_ORDER_CORRUPTED`.

---

## 5. Twelve Golden Arithmetic Verification Cases

The following 12 hand-checkable golden test fixtures provide exact mathematical baselines.
All intermediate calculations have been independently verified with high-precision Decimal arithmetic.

---

### Case 1: Standard Evaluation Sequence (Primary Fixture)
- **Input NAV Series:** $\text{NAV}_0 = 10000$, $\text{NAV}_1 = 11000$, $\text{NAV}_2 = 8800$, $\text{NAV}_3 = 9680$.
- **Declared Parameters:** $K = 252$, $rf_t = 0.0$ (explicit zero risk-free fixture).
- **Step 1: Periodic Returns:**
  - $r_1 = \frac{11000}{10000} - 1 = +0.10$ (+10.0%)
  - $r_2 = \frac{8800}{11000} - 1 = -0.20$ (-20.0%)
  - $r_3 = \frac{9680}{8800} - 1 = +0.10$ (+10.0%)
- **Step 2: Terminal Return:**
  - $R_{\text{terminal}} = \frac{9680}{10000} - 1 = -0.0320$ (-3.20%)
  - Compounding check: $(1 + 0.10) \times (1 - 0.20) \times (1 + 0.10) = 1.10 \times 0.80 \times 1.10 = 0.9680 = 1 - 0.0320$. (Exact match).
- **Step 3: Drawdown Profile:**
  - $t=0: \text{NAV}=10000, \text{peak}=10000, \text{dd}=0.0$
  - $t=1: \text{NAV}=11000, \text{peak}=11000, \text{dd}=0.0$
  - $t=2: \text{NAV}=8800, \text{peak}=11000, \text{dd} = \frac{8800 - 11000}{11000} = -0.2000$ (-20.0%)
  - $t=3: \text{NAV}=9680, \text{peak}=11000, \text{dd} = \frac{9680 - 11000}{11000} = -0.1200$ (-12.0%)
  - $\text{MDD} = -0.2000$ (-20.0%).
- **Step 4: Excess Returns and Sharpe Arithmetic:**
  - $e_1 = 0.10 - 0.0 = +0.10$
  - $e_2 = -0.20 - 0.0 = -0.20$
  - $e_3 = 0.10 - 0.0 = +0.10$
  - $\bar{e} = \frac{0.10 - 0.20 + 0.10}{3} = \frac{0.00}{3} = 0.00$
  - $s_e^2 = \frac{(0.10 - 0)^2 + (-0.20 - 0)^2 + (0.10 - 0)^2}{3 - 1} = \frac{0.01 + 0.04 + 0.01}{2} = \frac{0.06}{2} = 0.03$
  - $\text{sample\_std}(e) = \sqrt{0.03} \approx 0.17320508$
  - True Periodic Sharpe: $\frac{0.00}{\sqrt{0.03}} \times \sqrt{252} = 0.0000$.
- **Contrast with Legacy `performance.py` Bug:**
  - Legacy computes: $R_{\text{ann}} = (1 - 0.032)^{252 / 3} - 1 = (0.968)^{84} - 1 \approx -0.93490764$.
  - Legacy $\sigma_{\text{ann}} = \sqrt{0.03} \times \sqrt{252} \approx 0.17320508 \times 15.87450787 \approx 2.74954542$.
  - Legacy Sharpe: $\frac{-0.93490764}{2.74954542} \approx -0.34002262$. (Mathematically defective).
- **Expected Verification Output:**
  - $R_{\text{terminal}} = -0.0320$ (`KNOWN`)
  - $\text{MDD} = -0.2000$ (`KNOWN`)
  - $\text{Sharpe}_{\text{periodic}} = 0.0000$ (`KNOWN`)

---

### Case 2: Constant Cash Account (Zero Volatility)
- **Inputs:** $\text{NAV}_0 = 10000$, $\text{NAV}_1 = 10000$, $\text{NAV}_2 = 10000$. $rf_t = 0.0$.
- **Arithmetic:**
  - $r_1 = 0.0, r_2 = 0.0$.
  - $\bar{e} = 0.0, s_e^2 = 0.0, \text{sample\_std}(e) = 0.0$.
  - Sharpe: Division by zero standard deviation.
- **Expected:**
  - $R_{\text{terminal}} = 0.0000$ (`KNOWN`)
  - $\text{MDD} = 0.0000$ (`KNOWN`)
  - Sharpe = `UNDEFINED` (`ZERO_SAMPLE_VARIANCE`). Never zero.

---

### Case 3: One-Period Account History (Insufficient Observations)
- **Inputs:** $\text{NAV}_0 = 10000$, $\text{NAV}_1 = 10500$.
- **Arithmetic:**
  - $n = 1$. Sample variance requires $n \ge 2$ (degrees of freedom $n - 1 = 0$).
- **Expected:**
  - $R_{\text{terminal}} = +0.0500$ (`KNOWN`)
  - Sharpe = `UNAVAILABLE` (`INSUFFICIENT_OBSERVATIONS`).

---

### Case 4: Identical Positive Returns
- **Inputs:** $\text{NAV}_0 = 10000$, $\text{NAV}_1 = 10200$, $\text{NAV}_2 = 10404$. $rf_t = 0.0$.
- **Arithmetic:**
  - $r_1 = +0.02, r_2 = +0.02$.
  - $\bar{e} = +0.02$.
  - $s_e^2 = \frac{(0.02 - 0.02)^2 + (0.02 - 0.02)^2}{2 - 1} = 0.0$.
- **Expected:**
  - $R_{\text{terminal}} = +0.0404$ (`KNOWN`)
  - Sharpe = `UNDEFINED` (`ZERO_SAMPLE_VARIANCE`).

---

### Case 5: Large Loss Followed by Partial Recovery
- **Inputs:** $\text{NAV}_0 = 10000$, $\text{NAV}_1 = 5000$, $\text{NAV}_2 = 7500$. $rf_t = 0.0$.
- **Arithmetic:**
  - $r_1 = -0.50$, $r_2 = +0.50$.
  - $R_{\text{terminal}} = \frac{7500}{10000} - 1 = -0.2500$ (-25.0%).
  - Peak at $t=0$ is 10000. Trough at $t=1$ is 5000. $\text{MDD} = -0.5000$ (-50.0%).
  - At $t=2$, $\text{NAV}=7500 < 10000 \rightarrow$ Unrecovered.
  - $\bar{e} = \frac{-0.50 + 0.50}{2} = 0.0$.
  - $s_e^2 = \frac{(-0.50 - 0)^2 + (0.50 - 0)^2}{1} = 0.25 + 0.25 = 0.50$.
  - $\text{sample\_std}(e) = \sqrt{0.50} \approx 0.70710678$.
  - Sharpe = $\frac{0.0}{\sqrt{0.50}} \times \sqrt{252} = 0.0000$.
- **Expected:**
  - $R_{\text{terminal}} = -0.2500$ (`KNOWN`)
  - $\text{MDD} = -0.5000$ (`KNOWN`, recovery: `UNRECOVERED`)
  - Sharpe = $0.0000$ (`KNOWN`)

---

### Case 6: Missing Session Valuation Mark
- **Inputs:** Scheduled sessions $t=0, 1, 2, 3$. Valuation missing at $t=2$.
- **Expected:**
  - $r_2$ and $r_3$ = `UNAVAILABLE`.
  - Sharpe = `UNAVAILABLE` (`MISSING_VALUATION_MARK`).

---

### Case 7: Mixed or Irregular Session Spacing
- **Inputs:** Valuations at Day 0, Day 1, Day 5 (weekend + holidays). Calendar mapping declares trading sessions $t=0, 1, 2$.
- **Expected:**
  - If verified against trading calendar: valid periodic daily returns.
  - If unmapped calendar gaps exist: `UNAVAILABLE` (`IRREGULAR_SPACING`).

---

### Case 8: Zero Variance with Nonzero Excess Return
- **Inputs:** $\text{NAV}_0 = 10000, \text{NAV}_1 = 10100, \text{NAV}_2 = 10201$. $rf_1 = 0.005, rf_2 = 0.005$.
- **Arithmetic:**
  - $r_1 = 0.01, r_2 = 0.01$.
  - $e_1 = 0.01 - 0.005 = 0.005$, $e_2 = 0.005$.
  - $\text{sample\_std}(e) = 0.0$.
- **Expected:**
  - Sharpe = `UNDEFINED` (`ZERO_SAMPLE_VARIANCE`). Never $\infty$ or zero.

---

### Case 9: Negative Portfolio Return with Valid Volatility
- **Inputs:** $\text{NAV}_0 = 10000, \text{NAV}_1 = 9800, \text{NAV}_2 = 9702$. $rf_t = 0.001$.
- **Arithmetic:**
  - $r_1 = -0.02, r_2 = -0.01$.
  - $e_1 = -0.021, e_2 = -0.011$.
  - $\bar{e} = -0.016$.
  - $s_e^2 = \frac{(-0.021 - (-0.016))^2 + (-0.011 - (-0.016))^2}{1} = (-0.005)^2 + (0.005)^2 = 0.00005$.
  - $\text{sample\_std}(e) = \sqrt{0.00005} \approx 0.00707107$.
  - Sharpe = $\frac{-0.016}{0.00707107} \times \sqrt{252} \approx -2.26274170 \times 15.87450787 \approx -35.92$.
- **Expected:**
  - Sharpe = `KNOWN` (strictly negative real value, correctly reflecting underperformance).

---

### Case 10: Trading Cost Accounting Fixture (Three-Tier Attribution)
- **Inputs:**
  - Initial Capital = $10,000.00
  - Explicit Gross Gain = $+120.00$
  - Trading Transaction Costs = $\$160.00$ (embedded in platform net NAV)
  - Attributed Research Operating Costs = $\$80.00$ (Krish's verified receipts)
- **Arithmetic:**
  - View 1 (Gross Gain): $+120.00$
  - View 2 (Net Portfolio NAV Gain): $120.00 - 160.00 = -40.00$ ($\text{NAV}_T = 9960.00$, $R_{\text{net}} = -0.40\%$)
  - View 3 (Total Economic Gain): $-40.00 - 80.00 = -120.00$.
- **Expected:**
  - Net investment return: $-0.40\%$
  - Attributed operating costs: $\$80.00$
  - Total economic gain: $-\$120.00$.
  - Verification: Trading costs ($160) are subtracted only once; operating costs ($80) are deducted in View 3.

---

### Case 11: Unknown Operating Expense
- **Inputs:** Same as Case 10, but Krish's receipt has `amount_basis: "unknown"`.
- **Expected:**
  - View 2 (Net Portfolio NAV Gain): $-40.00$ (`KNOWN`)
  - View 3 (Total Economic Gain): `UNAVAILABLE` (`MISSING_OPERATING_COST`).
  - Portfolio NAV remains reportable while total economic scorecard is pending.

---

### Case 12: Independently Isolated but Correlated Arms
- **Inputs:** Arm B and Arm R evaluated across identical 126 observation sessions.
  - Paired difference series $d_t = r_t(B) - r_t(R)$.
- **Expected:**
  - Descriptive metrics computed per arm.
  - Paired differences evaluated without assuming independence between arms or across adjacent days.
  - Multiple comparison corrections applied prior to scientific claims.

---

## 6. Implementation Handoff and Migration Requirements

### 6.1 Affected Codebase Paths
The following existing files in the repository implement or test legacy performance calculations:
- `src/drift/domain/scorecards.py` (existing domain models).
- `src/drift/scorecards/performance.py` (`compute_return_and_risk`, `compute_drawdown_profile`).
- `tests/unit/test_scorecards_performance.py` (legacy unit tests asserting flawed Sharpe calculation).
- `tests/adversarial/test_m5_scorecards_adversarial.py` (adversarial tests exposing edge cases).

### 6.2 Migration Rules
1. **No Code Edits Under #382:** This is a documentation specification under #382.
   Source code modifications belong to a future, separately authorized implementation issue.
2. **Defect Tracking in #360:** M11 statistical missingness and promotion authorization
   defects remain tracked in GitHub issue #360.
3. **Backward Compatibility:** Persisted historical scorecards retain their original schema;
   new calculations apply to versioned `StrategyScorecardV2` profiles.
4. **Golden Fixture Tests:** The future implementation issue must include unit tests
   reproducing all 12 golden arithmetic cases exactly.

---

## 7. Document Acceptance Matrix

| Acceptance Requirement | Status in this Document | Verification Section |
|---|---|---|
| Correct periodic return definition | Complete | Section 2 (B1) |
| Distinct terminal compounding | Complete | Section 2 (B2) |
| Geometric annualization separated from Sharpe | Complete | Section 2 (B3) |
| True periodic excess-return Sharpe | Complete | Section 2 (B6) |
| Explicit undefined states (never zero) | Complete | Section 2 (B6, B8, B9), Section 4 |
| Three-tier financial reporting | Complete | Section 3 |
| Twelve golden arithmetic verification cases | Complete | Section 5 (Cases 1-12) |
| Hand-checkable primary fixture | Complete | Section 5 (Case 1) |
| Trading cost attribution fixture | Complete | Section 5 (Case 10) |
| Implementation handoff & #360 linkage | Complete | Section 6 |
| Zero Unicode em dashes (U+2014) | Enforced | Automated scan passed |
