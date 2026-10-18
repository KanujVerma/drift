# Stage 1 ETF universe and Balanced risk feasibility: research packet

**Status:** OWNER-LED RESEARCH PROPOSAL, **NOT** accepted numerical limits, a qualified data configuration, a runtime contract, or evidence of strategy profitability. Prepared October 16, 2026 under [#420](https://github.com/KanujVerma/drift/issues/420). The accepted strategy-selection direction is [S01-S38](stage1-decisions.md); the original broader [D01-D17](decisions.md) are separate and unchanged.

**Scope/evidence tiers:** (a) verified current strategy source at `main` `5583f112dfb45b8f6e8bc652de1cc4334ef8a247`; (b) fund issuer public fact pages establishing fund types and dates, **not** licensed historical market-data provenance; (c) exhaustive mathematical **structural** selection feasibility from current source semantics; (d) candidate risk limits requiring further model, platform and statistical acceptance. This research **did not** request authenticated data from a broker/provider, simulate historical realized ETF prices, verify bid/ask history, measure real strategy-selection frequencies, or trade.

## Executive findings

1. All twelve proposed funds **launched by 2010**, so the fund-existence requirement is compatible with historical periods starting in 2021 in principle. **Qualified, retained and entitled market histories are not established.** For the intended scored start after 253 warmup + 126 observations, source coverage is needed substantially before the first scored date.
2. Current B3 targets equal dollars in **all twelve ETFs** at a rebalance, approximately 50% equities / 41.67% fixed income / 8.33% gold before whole-share rounding. Current B4 and B5 select the highest/lowest-ranked **ceil(n/2)** eligible tickers and equal-weight them, six positions at about **16.67% per ETF** when all twelve are eligible.
3. The unaccepted **Balanced fixture** in [Matthew's draft mandate #414](https://github.com/KanujVerma/drift/pull/414) describes 15% maximum ETF weight, 15%/$1500 absolute position notional on $10k, 80% maximum gross exposure, $1000 maximum order notional, 10-share order size, 2 orders/minute and 10% trailing drawdown. These are expressly **illustrative, not approved**. They conflict with intended roughly 100%-invested B3 and 16.67%-per-ETF B4/B5 portfolios, and may obstruct opening switches even if sliced into multiple orders.
4. A **test candidate**, not a final mandate, is maximum **20% per ETF, 70% total equities, 75% total fixed income, 20% gold and 100% gross invested exposure**, with zero leverage/shorting and no mandatory asset-class minimum. Of all `C(12,6)=924` possible equally weighted six-fund combinations, **880/924 (95.24%)** meet those structural caps. This is **not** a time-series backtest or an empirical 95% success/acceptance probability.
5. Historical B4 momentum can preferentially select many equities simultaneously, while B5 low volatility can select many fixed-income products. The disallowed 44 six-name combinations may have very high **real monthly probability** under correlated ranking. A qualified **development-only historical feasibility sweep is mandatory** before accepting any class limits.
6. Need a separate deterministic rule for incoming target rejection versus minimum-trim overlay, and for mandatory correction of existing drift violations. Current per-order `HardRiskGatekeeper` is not a target-weight class-budget engine or a protective sell scheduler; a latched kill switch rejects even protective orders unless a new independently approved handling contract says otherwise.

## 1. Twelve proposed funds, broad role and public issuer evidence

| Type | ETF | Intended broad exposure | Issuer-reported inception | Current venue note and primary issuer source |
| --- | --- | --- | --- | --- |
| US equity | **VOO** | S&P 500 large US stocks | 2010-09-07 | [Vanguard VOO](https://advisors.vanguard.com/investments/products/voo/vanguard-sp-500-etf) (US market; NYSE Arca listing to reconfirm historical MIC). |
| US equity | **IJH** | S&P MidCap 400 | 2000-05-22 | [iShares IJH](https://www.ishares.com/us/products/239763/ishares-core-sp-midcap-etf), currently NYSE Arca. |
| US equity | **IJR** | S&P SmallCap 600 | 2000-05-22 | [iShares IJR](https://www.ishares.com/us/products/239774/ishares-core-sp-smallcap-etf), currently NYSE Arca. |
| US equity | **QQQ** | Nasdaq-100, nonfinancial, growth/technology tilted | 1999-03-10 | [Invesco QQQ](https://www.invesco.com/qqq-etf/en/home.html); verify the historical listing MIC, index membership and VOO overlap. |
| International equity | **VEA** | Developed markets ex US | 2007-07-20 | [Vanguard VEA](https://advisors.vanguard.com/investments/products/vea/vanguard-ftse-developed-markets-etf), currently NYSE Arca. |
| International equity | **VWO** | Emerging markets | 2005-03-04 | [Vanguard VWO](https://advisors.vanguard.com/investments/products/vwo/vanguard-ftse-emerging-markets-etf), currently NYSE Arca. |
| US Treasury | **SHY** | Short 1-3 year Treasury duration | 2002-07-22 | [iShares SHY](https://www.ishares.com/us/products/239452/), currently NASDAQ. |
| US Treasury | **IEF** | Intermediate 7-10 year Treasury duration | 2002-07-22 | [iShares IEF](https://www.ishares.com/us/products/239456/ishares-7-10-year-treasury-bond-etf), currently NASDAQ. |
| US Treasury | **TLT** | Long 20+ year Treasury duration | 2002-07-22 | [iShares TLT](https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf), currently NASDAQ. |
| Inflation-linked bond | **TIP** | US Treasury inflation-protected bonds | 2003-12-04 | [iShares TIP](https://www.ishares.com/us/products/239467/ishares-tips-bond-etf), currently NYSE Arca. |
| Credit bond | **LQD** | USD investment-grade corporate bonds | 2002-07-22 | [iShares LQD](https://www.ishares.com/us/products/239566/ishares-iboxx-investment-grade-corporate-bond-etf), currently NYSE Arca. |
| Gold exposure | **GLD** | Physically backed SPDR Gold Trust | 2004-11-18 | [GLD issuer](https://www.spdrgoldshares.com/usa/gld/), currently NYSE Arca; **trust**, not a stock/bond index fund. |

**Important qualitative overlap and risk:** QQQ shares major US large-company exposures with VOO, so the two fund allocations do not create independent economic diversification. SHY, IEF and TLT share Treasury-rate sensitivity but have markedly different duration risk; TIP adds real-rate/inflation-linked exposure; LQD adds corporate credit risk and also has rate duration. Gold can diversify certain shocks but has its own volatile price. These classifications are for **first-pass caps** only. Aggregate portfolio volatility, factor concentration, rate duration, correlations, constituents and point-in-time issuer index composition remain to be measured, not presumed. The word "Balanced" does not establish suitability to any actual investor.

**Current issuer expense ratios versus trading cost:** Issuer public fund operating expense ratios reflect ongoing fund economics, generally already represented in historical tradable NAV/market-return series; do **not** debit them again if the observed share prices or total returns already contain these expenses. Portfolio trading costs (spread, market impact/slippage, commissions if applicable) and model/data/inference costs are different ledgers. Published **2026** bid/ask or trading volumes are not historical spreads for 2021-2025.

**Venue, calendars and data gate:** Existing [#365](https://github.com/KanujVerma/drift/issues/365) identifies current ARCX/NYSE Arca representation and cross-venue calendar limits, with multiple candidate funds on NYSE Arca versus NASDAQ. Current venue reports are not a point-in-time venue-ID series. [#378](https://github.com/KanujVerma/drift/issues/378) must establish data provider identity, access/redistribution rights, calendars, prices, bid/ask quality, splits/distributions, source revisions and actual first-available times before a historical study. The previous QQQ-only replay and a vendor's public marketing performance page are **not** qualifications of this twelve-fund universe.

## 2. Exact current strategy math and evidence

- [B3 reference source](../../../src/drift/baselines/b3_monthly_equal_weight_rebalance.py): equal target dollars per admitted security, whole shares rounded down, cash residual. Existing default month-end detection is a weekday heuristic, not a complete exchange holiday calendar. Must supply validated rebalance dates/contract at integration. Do not silently mutate the baseline to make Stage 1 work.
- [B4 reference source](../../../src/drift/baselines/b4_momentum.py): `close[t-21] / close[t-252] - 1`, at least **253** completed sessions, select **top ceil(n/2)** by *relative* momentum; no absolute positive-momentum requirement, no strategic all-cash option. Whole-share equal targets.
- [B5 reference source](../../../src/drift/baselines/b5_low_volatility.py): at least **61** sessions, exact population variance over 60 completed return observations, select **bottom ceil(n/2)**. Whole-share equal targets.
- **Trading-frequency confounder:** B4 and B5 recalculate portfolio targets on each evaluator decision invocation, with no B3-like internal monthly rebalance gate in the inspected source. Thus a monthly **AI switch** schedule does **not** imply monthly **investment trading**, and ongoing B4/B5 re-targeting can create substantial turnover even when no AI switch happens. Measure strategy-internal turnover separately from AI switch turnover; do not change frozen B4/B5 cadence merely to make their trading costs look lower.
- Missing history can result in empty target tuples under the current implementation. Stage 1 must distinguish **ineligibility/invalid evidence** from an intentional empty portfolio and never convert an unavailable signal into involuntary liquidation.
- Reference B3/B4/B5 results are independent shadow/accounting records. The AI portfolio is a separate USD 10,000 book with fresh scored capital after **253 warmup + 126 observation sessions**. Inferred gross exposures assume continuous target dollars **only for mathematical feasibility**; actual whole-share rounding and costs need separate evaluation.

For all twelve eligible: `B3 = 6/12 equity + 5/12 bond + 1/12 gold`; `B4/B5 = six selected × 1/6 approximate target invested exposure per fund`.

The **11-fund no-QQQ sensitivity** contains five equities, five bonds and gold. Its B3 baseline is approximately **45.45% equity / 45.45% bonds / 9.09% gold**. Because B4/B5 still select `ceil(11/2)=6`, each selected fund still targets approximately 16.67% of NAV, subject to rounding. The sensitivity is preregistered rather than chosen for past returns.

## 3. Exhaustive structural feasibility, no price-series assumptions

**Method:** Enumerate all unordered subsets of six distinct ETFs from the 12 eligible symbols, with equal **target notional** of `1/6` for each selected name. For each subset, check the individual ETF cap and sum exposure of member symbols by the fixed equity/fixed-income/gold classes. This represents B4/B5 **possible selected sets**, not their observed rankings. No market history, returns, stochastic trials, weighting of combinations or timing is assumed.

The count `C(12,6) = 924`. For the proposed 70% equity / 75% bonds / 20% gold caps with 20% individual cap:
- Six-name selections containing **5 or 6 equities** violate equities: `C(6,5)*C(6,1) + C(6,6) = 36 + 1 = 37`.
- Selections with **all five bonds** violate the 75% bond cap: `C(5,5)*C(7,1) = 7`.
- Those two violations cannot coexist in a six-name subset, so **44 subsets fail, 880 pass (95.24%)**.
- A single gold selection is `1/6 = 16.67%`, below 20%, while a 15% gold cap disallows almost every six-fund target containing GLD. A 15% individual ETF cap disallows all six-name targets under the exact continuous-weight assumption.

| Synthetic structural policy | B4/B5 permitted 6-name subsets | Excluded, without ranking probabilities |
| --- | ---: | --- |
| ETF <=15%, E<=70%, bonds<=75%, gold<=20% | **0 / 924** | All include a target 16.67% ETF. |
| ETF <=20%, **E<=65%**, bonds<=75%, gold<=20% | **655 / 924 (70.89%)** | Four or more equities, or five bonds. |
| ETF <=20%, **E<=70%**, bonds<=75%, gold<=20% | **880 / 924 (95.24%)** | Five/six equities, or five bonds. **Recommended for development sensitivity, not accepted.** |
| ETF <=25%, E<=70%, bonds<=75%, gold<=20% | **880 / 924 (95.24%)** | Same class-composition selection set, weaker ETF drift protection. |
| ETF <=25%, E<=85%, bonds<=85%, gold<=20% | **923 / 924 (99.89%)** | Only all six equities. Class caps nearly nonbinding. |
| ETF <=20%, E<=70%, bonds<=75%, **gold<=15%** | **425 / 924 (46.00%)** | All gold-containing sets fail, plus equity/bond exclusions. |

**No-QQQ structural check:** For the 11-ETF configuration, there are `C(11,6)=462` equally weighted six-name subsets; **450/462 (97.40%)** meet the proposed 20/70/75/20 policy. Six subsets hold five equities and six hold five bonds and fail; no overlap.

**Interpretation restriction:** `880/924` is **not** an estimated probability of accepting B4 or B5 in any historical month. Market returns, correlations, index composition and relative volatility make fund rankings highly non-uniform. For example, a high-growth regime may repeatedly put **5 or 6 equities** in B4's top six; a low-volatility regime may repeatedly put **all five fixed-income funds** in B5's bottom six. Both would often be blocked under the proposed policy. That is the core empirical question; do **not** call 95.24% an acceptance rate or proof of Balanced risk protection.

**Reproducibility of the counts (pure Python, no market data):**

```python
from itertools import combinations

equity = {"VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"}
bonds = {"SHY", "IEF", "TLT", "TIP", "LQD"}
gold = {"GLD"}
universe = sorted(equity | bonds | gold)


def valid(selected, *, equity_cap=0.70, bond_cap=0.75, gold_cap=0.20, etf_cap=0.20):
    n = len(selected)
    return (
        (1 / n) <= etf_cap
        and len(set(selected) & equity) / n <= equity_cap
        and len(set(selected) & bonds) / n <= bond_cap
        and len(set(selected) & gold) / n <= gold_cap
    )


sets12 = list(combinations(universe, 6))
assert len(sets12) == 924
assert sum(valid(s) for s in sets12) == 880
assert sum(valid(s, equity_cap=0.65) for s in sets12) == 655
assert sum(valid(s, gold_cap=0.15) for s in sets12) == 425
assert sum(valid(s, etf_cap=0.15) for s in sets12) == 0
assert (
    sum(valid(s, equity_cap=0.85, bond_cap=0.85, etf_cap=0.25) for s in sets12) == 923
)
sets11 = list(combinations([t for t in universe if t != "QQQ"], 6))
assert len(sets11) == 462
assert sum(valid(s) for s in sets11) == 450
```

Counts were independently crosschecked through both a Python enumeration and separate JavaScript enumeration of the same unordered equal-target portfolios. Historical and execution results were **not** generated.

## 4. Numerical Balanced proposal for **further testing only**

| Policy | Proposal | Reason and unresolved requirement |
| --- | --- | --- |
| Universe | 12 candidate ETFs as above | The 11-fund no-QQQ variant is a separately named sensitivity, **not** a search over the best past universe. All funds need source/venue eligibility before scoring. |
| Single ETF | **20% NAV max** | All six-name initial equal targets fit; tighter than an arbitrary 25% cap once holdings drift. Test actual whole-share, stale-price and marking behavior. This cap alone does **not** resolve VOO/QQQ factor overlap. |
| Total equities | **70% NAV max** | B3's intended 50% equity fits, four of six equal B4/B5 equities fits (~66.67%), five of six (~83.33%) does not. Research how often B4 is blocked in different development regimes. |
| Total fixed income | **75% NAV max** | B3's ~41.67% fits; B4/B5 may hold four of six bonds (~66.67%) but five (~83.33%) is disallowed. Test whether low-volatility B5 becomes effectively unusable in practice. |
| Gold | **20% NAV max** | One selected GLD at ~16.67% remains possible; 15% would often structurally disallow gold selection. |
| Gross invested | **100% NAV maximum** | No leverage and no shorting, with actual costs/rounding often leaving residual cash. Do not require a minimum invested percentage; no AI discretionary cash selection. Pending buys/sells and reserved funds need atomic target checks. |
| Asset-class minimums | **None** | Reflect S26; no additional manager overriding strategy to force bond/gold floors. |
| Turnover/order caps | **Not yet proposed numerically** | A B3-to-B4 transition can legitimately require many sells/buys. Bound actual trading costs and test order splitting/cash availability before choosing limits; published ETF daily fund turnover is not strategy turnover. |
| Drift correction | **Required separately** | After an actual limit breach, compute the minimum valid whole-share sale(s) at next eligible simulated execution opportunity using fresh accepted state. Track reason, costs, fills, refusal; no assertion that a price gap cannot breach the cap temporarily. |
| Incoming risk violation | **Primary reject; secondary deterministic trim** | A class breach can exist with **no** individually violating fund. Example: six equities each at ~16.67% exceed the 70% **class** limit, not the 20% ETF limit. A class-only proportional reduction **within the offending asset class** may be reasonable, but tie order, rounding and redistributions require owner/producer review. Never silently scale the **whole** portfolio. |
| Volatility and drawdown | **Report in primary; separately study dynamic overlay** | Do not turn unaccepted 10% trailing drawdown fixture into a main-study forced cash/irreversible halt. Any mandatory platform kill switch, protective de-risk/containment and re-entry must be versioned, specified and applied equally to relevant competitors. |
| Trading cost/fee | **Separate R3 research** | Use qualified fill assumptions, identical accounts, explicit cash yield, share rounding and no duplicated fund expense debit. |
| Approval | **Unapproved** | This table is a research hypothesis; required empirical checks and independent approvals remain outstanding. |

**Why test 20% versus 25% individual caps?** Under a simplified six-fund equal-weight portfolio where only one fund rises and all others remain unchanged, its new fraction is `x/(x+5)` for relative price multiplier `x`. It reaches 20% at `x=1.25` (+25% relative move), but 25% at `x=5/3` (+66.67%). These are **illustrative drift thresholds**, not typical expected one-month moves, and actual rebalancing/fees affect the calculation.

**Why 70/75/20 is a test candidate rather than an investor mandate:** CFA's [Principles of Asset Allocation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/principles-asset-allocation) and [Active Equity Portfolio Construction](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/active-equity-investing-portfolio-construction) discuss concentration constraints and diversified risk sources, but neither establishes universal numerical percentages. ETF-count balance is not risk parity. Independent realized volatility, drawdown, correlation, exposure and turnover measurement is required. Volatility targeting is a separate scientific hypothesis, not an automatic improvement: see Moreira and Muir (2017), [Volatility-Managed Portfolios](https://afajof.org/issue/volume-72-issue-4/), and [Vanguard's threshold-rebalancing research](https://workplace.vanguard.com/insights-and-research/perspective/portfolio-rebalancing-navigating-volatility-in-vanguard-target-retirement-funds.html).

## 5. Producer implementation conflicts and mandatory gates

### A. The unaccepted fixture Balanced mandate cannot be copied as Stage 1 policy

[Draft #414](https://github.com/KanujVerma/drift/pull/414) labels the Conservative/Balanced/Aggressive values as unaccepted examples. For a USD 10,000 reference account:
- 15% / $1,500 single-position ceiling conflicts with a theoretical fully invested six-fund B4/B5 sleeve of ~$1,666.67.
- An 80% gross invested ceiling conflicts with B3's theoretical 100% fully invested equal-weight target and the six-fund targets. Actual whole-share cash drag does **not** justify treating these values as operationally compatible.
- $1,000 per-order notional / 10-share quantity / 2 new orders per minute may require coordinated splitting of even allowed initial targets, yet the simulator must still satisfy next eligible open, no duplicate fills and exactly reconciled portfolio costs. Splitting cannot bypass mandatory effective risk authority.
- A proposed 10% trailing drawdown trip could dominate portfolio results or stop future protective risk-reducing trades. The meaning of mandatory platform containment must be separately resolved, not copied into an investment research preset.

**Owner action:** Request Matthew's independent review and a distinct, explicitly approved Stage 1 research profile using the stricter-of mandatory system safeguard and owner-accepted mandate. Do **not** edit Matthew's draft or assert the staged policy is already implemented.

### B. Historical ranking and execution gating to run before numeric freeze

Build a *development-only* result for each eligible month, using qualified source-time cutoff and exact B4/B5 algorithms:
1. Record **each** selected fund and 12-name eligibility completeness; if any required input is unavailable, mark the strategy ineligible, **never** implicitly reduce its menu or liquidate on an empty intent.
2. Count months satisfying each candidate fixed mandate, **by strategy and year/market regime**; log class mix, real selected gross/asset exposures and close-to-next-open transition date. A structural subset count alone is insufficient.
3. For the initially valid targets, calculate **actual whole-share executable weights**, residual cash, order size, restrictions, and whether each transition is possible under accepted portfolio and execution state.
4. Measure valid months, rejection/abstention rates, switch count, turnover, slippage sensitivity, ETF/class breaches between checkpoints, automatic drift-correction fills and their costs.
5. Include no-QQQ 11-fund sensitivity without retrospective universe promotion. Run a *development-only* sweep of more/less restrictive caps, e.g. 65/75/20 and 85/85/20, recording how the risk limit changes the AI/R menu and exposure.
6. Report actual portfolio volatility, drawdown and asset correlations. Any model training or threshold selection must not use final scored evaluation or a claimed pristine 2025 holdout. Model pretraining contamination remains an explicit limit.
7. Only then fix **Balanced** numerical limits, effective system ceilings, risk-engine behavior and scientific evaluation under owner approval plus Matthew/Harsha domain acceptance. G1-G3 in [Stage 1 roadmap](stage1-roadmap.md) apply before scoring.

### C. Risk-engine contract gaps to resolve independently

Current [RiskPolicyV1](../../../src/drift/domain/risk.py) has ETF weight/gross/order/drawdown fields, but not asset-class or turnover policy. Current [HardRiskGatekeeper](../../../src/drift/risk/gatekeeper.py) checks individual orders, optional portfolio state, projected weights for buys and a persistent kill switch. It does **not** independently schedule existing-risk corrections, enforce class caps on a proposed net target portfolio, or allow protective sells after a kill-switch trip.

Require **fail-closed complete state**, order-atomic projected target exposure (including reserved/in-flight quantities and cash), selling/buying sequencing, valid partial/unfilled/UNKNOWN results, class-overlap and tag mapping, correction resolution/cash semantics, explicit protective exceptions under approved containment, and independent negative-path tests. See [#380](https://github.com/KanujVerma/drift/issues/380), [#411](https://github.com/KanujVerma/drift/issues/411), [#395](https://github.com/KanujVerma/drift/issues/395) and [#396](https://github.com/KanujVerma/drift/issues/396). A deterministic risk engine is a mandatory separate authority; AI must never override it.

## 6. Required independent acceptance and immediate next action

- **Kanuj:** Evaluate whether 20/70/75/20 is an appropriate **development-study candidate**, not as a real investor risk preset; reserve final numerical judgment until the empirical feasibility matrix and reviewer feedback exist.
- **Matthew:** Read the published compatibility findings against draft #414 and platform sources; propose schema/versioned enforcement semantics for class caps and meaningful target-level protection. Qualify ETF data/rights, corporate actions and NYSE Arca/NASDAQ calendar support via existing platform issues. **Do not** silently replace unaccepted draft fixture numbers with this proposal.
- **Krish:** Verify B3/B4/B5 exact strategy decision representations, common eligibility gate and potential regime-concentrated B4/B5 rankings; define development-only synthetic and later qualified historical target reports under accepted contracts.
- **Harsha:** Audit the structural enumeration and prevent misinterpretation as an historical acceptance rate; require actual rejected-switch/regime metrics and statistically valid, risk-comparable primary campaign. Review only after access and independent-review conditions are met.

**Stop condition:** Until source histories/rights, target-execution/risk contracts, R's definition, costs, scientific metrics and numerical approvals are accepted, **no scored backtest**, no inferred economic return advantage, no real/paper trading and no unauthorized external data or model spending. This packet is a bounded proposal for independent review.

## Source-reference links

First-party fund sources: [Vanguard VOO](https://advisors.vanguard.com/investments/products/voo/vanguard-sp-500-etf), [Vanguard VEA](https://advisors.vanguard.com/investments/products/vea/vanguard-ftse-developed-markets-etf), [Vanguard VWO](https://advisors.vanguard.com/investments/products/vwo/vanguard-ftse-emerging-markets-etf), [iShares IJH](https://www.ishares.com/us/products/239763/ishares-core-sp-midcap-etf), [iShares IJR](https://www.ishares.com/us/products/239774/ishares-core-sp-smallcap-etf), [Invesco QQQ](https://www.invesco.com/qqq-etf/en/home.html), [iShares SHY](https://www.ishares.com/us/products/239452/), [iShares IEF](https://www.ishares.com/us/products/239456/ishares-7-10-year-treasury-bond-etf), [iShares TLT](https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf), [iShares TIP](https://www.ishares.com/us/products/239467/ishares-tips-bond-etf), [iShares LQD](https://www.ishares.com/us/products/239566/ishares-iboxx-investment-grade-corporate-bond-etf), [GLD trust](https://www.spdrgoldshares.com/usa/gld/). Sources are public descriptions accessed/reviewed October 16, 2026; not proof that corresponding historical raw market bars may be used or redistributed.
