# Adaptive experiment decisions and rationale

## Status and meaning

These 17 decisions record Kanuj's approvals in the October 12, 2026 design
conversation. They are accepted product/research direction. Repository effect
begins when the adopting ADR and coordination PR merge. They are not evidence
of completed code, approved data access, profitable strategies, or trading
permission. Numerical parameters and wire contracts identified as unresolved
below are not silently approved by this document.

Terminology: MVP-BOUNDED is the previously discussed architecture Option B;
FUTURE-GENERATED is architecture Option C. These are not the same labels as
experimental portfolio B (adaptive AI) or C (passive market benchmark).

## D01. Bounded MVP, extensible to generated strategies

Decision: Begin with selection among approved strategy families, approved
parameter ranges, and target allocations. Do not generate or execute arbitrary
strategy code in the MVP. Later, permit generated strategies through a separate
sandbox, validation, and eligibility process.

Why: Establish a testable product before introducing a larger code-search
space. The data, accounting, execution, results, and experiment interfaces must
not need replacing when the proposal producer changes. Existing B0-B5 baseline
definitions remain frozen controls; a tunable variant receives its own identity.

## D02. Market data first; news is a first-class input

Decision: Complete the market-data baseline foundation, while designing for
news, authorized social sources, filings, and other timestamped information
from the beginning. Add these inputs through replaceable source/analysis
adapters, not ETF-specific or vendor-specific strategy logic.

Why: Prices alone do not explain new information. Additional information must
be measured for usefulness, not assumed useful. Historical content revisions
and model pretraining leakage remain explicit limitations.

## D03. Significant events trigger extra review

Decision: Potentially important events can trigger an additional AI review
without waiting for the regular schedule. A trigger requests analysis, not an
order. Preserve source evidence, first-observed time, revisions, and uncertainty.

Why: Event-driven decisions are part of the intended product. Immediate review
is not a claim of instantaneous execution, guaranteed source truth, or profit.
FinGPT-style extraction/context retrieval may be evaluated behind this boundary.

## D04. Separate monitoring, review, adaptation, and execution clocks

Decision: Use weekly routine portfolio reviews, monthly planned strategy and
parameter updates, and event-triggered reviews. Monitor market/risk state at
the cadence supported by the feed. Existing approved strategies may generate
eligible trades when their rules require them. A weekly review is not a
mandatory weekly trade or automatic monthly-strategy rewrite.

Why: Avoid equating analysis frequency with turnover. Keep the scheduling
policy configurable and compare alternatives under preregistered conditions.
Exact weekdays, cutoffs, time zones, cooldowns, and stale-decision lifetimes
must be specified before a campaign, not chosen opportunistically during it.

## D05. Test full event response and defensive-only response

Decision: Event reviews may propose hold, reduce, increase, or reallocate within
the authorized universe and mandate. Support a separately named defensive-only
policy as an experimental comparison. It is not the sole product behavior.

Why: Selling after bad news can be wrong just as buying after good news can be
wrong. Compare net outcomes rather than assume defensive trading is superior.
Both policies use identical evidence and execution rules. Defensive-only is a
precise permitted-action policy, not a guarantee that realized risk decreases.

## D06. Intraday-capable adaptive experiments, including extended hours

Decision: The first event-driven adaptive experiment should support regular,
pre-market, and after-hours simulated execution when appropriate data and
capabilities are present. Defer full overnight support until separately
verified. Preserve next-session execution as a comparison and explicit fallback.

Why: Waiting until the next day would test a different news strategy. But daily
bars cannot establish intraday fills. Preserve the existing daily evaluator
protocol and introduce a versioned, reviewed timing/execution extension. Model
receipt, analysis, risk-check, submission and fill times; spread, latency,
liquidity, partial fills, halts and unfilled orders. Unsupported execution is
reported as unavailable, not silently filled at an attractive historical price.

## D07. Maximize expected net returns within a mandate

Decision: Optimize expected return after disclosed trading, inference, compute,
and data costs within user-defined risk preferences and mandatory system
safeguards. Measure both incremental AI value versus R and investment value
versus passive benchmark C.

Why: A higher gross return may reflect higher risk or greater spending. Risk
thresholds are controls, not guarantees of maximum loss. Report actual and
appropriately risk-matched comparisons without relabeling an altered passive
benchmark as ordinary buy-and-hold.

## D08. Three risk presets plus Advanced settings

Decision: Offer Conservative, Balanced, and Aggressive presets with optional
advanced customization. The presets supply a versioned investment mandate to
the same risk engine; they do not create three engines. Use one preregistered
Balanced mandate for the primary comparison, with other profiles as secondary
experiments. Numerical thresholds are not yet approved.

Why: Keep the basic experience simple without sacrificing control. AI cannot
change the mandate or disable mandatory protections. Higher tolerated risk
does not guarantee higher return. Mandate changes are explicitly authorized,
versioned, and create a new experimental condition when relevant.

## D09. Hybrid event detection

Decision: Lightweight screening identifies potentially relevant inputs; deeper
AI analysis determines significance and portfolio implications. Important
primary-source announcements may warrant review without waiting for price
confirmation. Deduplicate and rate-limit reviews without hiding materially
changed or corrected stories.

Why: Avoid both missing important news and paying for a full LLM review of every
headline. Sentiment, credibility, novelty, and market significance are different
attributes. News/social text is untrusted input, never executable instructions.

## D10. Diversified ETF universe first

Decision: Use roughly 10-15 liquid, diversified ETFs for the adaptive experiment,
selected under documented eligibility and historical-availability rules.
Support individual stocks later through security-neutral interfaces. No
leverage, shorting, options, or crypto is introduced in this MVP.

Why: Give news-driven allocation meaningful choices without immediately adding
hundreds of instruments. Do not select the universe by hindsight profitability.
The exact list is not approved. The existing smaller baseline campaign remains
a separate task; a larger universe does not expand an active PR's write-set.

## D11. Historical and prospective evidence

Decision: Use development, validation, an untouched historical holdout, and
forward paper/shadow observation before claiming an advantage. Intended date
roles are 2021-2023 development, 2024 validation, and 2025 holdout, restricted to
actually supported data. A provider evidence floor must not be weakened to fit
these dates. Acquire additional warmup data only under honest source limits.

Why: Historical results are vulnerable to selection and model pretraining
leakage. A year is not an untouched holdout merely because a document calls it
one. Audit access and tuning history. Mark contaminated/unverifiable holdouts;
do not reuse them as pristine confirmation. Forward broker-connected operation
requires separate authorization; an approved design does not provide it.

## D12. Separate information value from decision-maker value

Decision: Compare AI and conventional optimization with matched information,
assets, risks and opportunities. Separately compare AI with and without news.

Why: Otherwise extra information can be mistaken for better decisions. If both
arms share an LLM-derived event signal, the comparison measures the additional
AI allocation/selection layer, not a completely AI-free system. Attribute shared
signal costs transparently. Separate a matched-review-timing news-content test
from a total news-system test where trigger times may also differ.

## D13. Three complementary research-budget tests

Decision: Run (1) same candidate set, different selectors; (2) independently
searched candidates with matched evaluation opportunities; and (3) flexible
research under predefined spending/compute ceilings. The flexible test is
closer to intended operation, but does not replace the controlled tests.

Why: Better outcomes can come from selection, better search, or simply more
trials. Record failed, invalid, duplicate, and rejected attempts as well as
winners. Equal evaluation counts are not equal cost or independent samples.
Avoid claiming any winning arm proves superior internal reasoning.

## D14. Freeze the learning method, not the evolving state

Decision: During a campaign, adaptation may change strategy choices, permitted
parameters, allocations, research priorities, and time-eligible memory. The
learning algorithm, provider/model version, prompts, retrieval rules, permitted
tools, budgets, constraints, and success criteria stay versioned and fixed.

Why: We must evaluate an adaptive process without changing the measuring rules
mid-test. A new learning method or silent model-version change creates a new
campaign version. Retain actual model requests/responses for replay; do not
assume a fresh stochastic API call reproduces a previous answer.

## D15. Stage new-strategy eligibility without delaying ordinary reactions

Decision: Newly discovered or materially changed strategies require historical
validation, prospective evidence, independent eligibility review, and ongoing
monitoring. Approved strategies may react to news inside their permitted
parameter/action envelope without restarting that process for every trade.

Why: Fast reaction and safe introduction of new code are different problems.
A change outside an approved envelope is a new candidate. Generated code later
requires additional isolated security/correctness testing. Paper eligibility,
scientific qualification, and live deployment authority are separate states.

## D16. Evidence-based acceptance

Decision: Preregister a minimum forward duration, meaningful evidence quantity,
risk/cost tests, uncertainty/multiple-testing treatment, and fixed review
schedule. Do not approve merely because a fixed number of days passed.

Why: Correlated observations and many trials can exaggerate confidence.
Thresholds must be decided before looking at confirmation outcomes. Passing a
stage supports eligibility at that stage, not guaranteed profit. Missing
required evidence must never default to favorable statistics.

## D17. Customizable approval friction; non-bypassable safeguards

Decision: Support Ask every time, Smart approval, and Auto-approve within a
previously authorized mandate. Smart thresholds are measurable, not based only
on model self-confidence. Simulation campaigns normally use auto-approval within
their frozen mandate. Any eventual real-money deployment requires separate
explicit authorization and validated operations; initial manual approval is the
proposed default, not current permission to connect a broker.

Why: Fast events are incompatible with mandatory human approval of every paper
trade, but auto-approval is not unlimited authority. No mode disables risk,
source, execution, or emergency controls. A user pause blocks new risk-taking
submissions; it does not promise existing orders are cancelled or liquidate
holdings. Pending-order cancellation, in-flight fills and resumption require a
separately specified state transition and reconciliation policy.

## Deliberately unresolved release parameters

The exact ETF list; risk/turnover/position/spread thresholds; provider selection,
rights and entitlements; model versions and budgets; review timing and TTLs;
optimizer algorithm/search space; minimum forward duration and statistical
thresholds; approval expiry; pause/cancel/reconciliation details; news retention;
and final wire schemas need owner-produced specifications and acceptance.

No agent may fill these with guessed production defaults. Missing configuration
blocks the dependent experiment, not unrelated design or fixture-only work.
The product decisions are frozen; these implementation parameters are not.

## Ownership record, separate from D01-D17

D01 through D17 and the rationale above are unchanged by the four-person
ownership amendment accepted on 2026-10-12. That amendment is not a new product
decision and it does not renumber this register. Accountable owners, producer
routing and the reason for the split are in
[workstreams](../workstreams.md), [ADR 0015](../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
and the [requirements crosswalk](requirements-crosswalk.md).
