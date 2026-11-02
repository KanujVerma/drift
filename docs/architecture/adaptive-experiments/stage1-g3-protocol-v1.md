# Stage 1 G3 protocol v1: locked design and explicit admission requirements

**Design date:** 2026-11-01, America/Chicago. **Scope:** the owner-delegated
G2 completion and G3 preparation in [#578](https://github.com/KanujVerma/drift/issues/578).

This revision locks the research choices and calibration procedures below.
It does not claim that qualified historical inputs, fitted comparator
coefficients, an immutable model deployment, original independent acceptance
receipts, or a successful study already exist. The executable distinction
between a draft, a verified freeze and study readiness remains the one in
[the G3 freeze contract](stage1-g3-freeze.md). A locked design is an input to
that contract, not a substitute for its admission checks.

The owner authorized best-interest implementation and research design choices
in this pass. Numerical choices newly fixed here are research policy choices;
they are not represented as prior producer acceptance or empirically validated
risk limits. Changing a choice after observing validation or scoring results
requires a new version and a new, untouched evaluation opportunity. No Gemini
or Cursor review, issuer signature, data license, or historical holdout audit
is inferred from that owner authorization.

## 1. Question, periods and the meaning of a result

The primary question remains whether a fixed-model AI selector, B, adds net
economic value over deterministic selector R when both choose from the same
installed B3/B4/B5 family menu under the same executable account rules.
[S01-S38](stage1-decisions.md), [the methodology](methodology.md), and
[the metric contract](metric-contract.md) remain the source of the shared
research intent. This document resolves the implementation choices below
without granting broker or real-capital authority.

The primary NAV endpoint is B's terminal net return minus R's terminal net
return. The total-economic view multiplies that difference by initial capital
and subtracts attributable incremental operating costs. Both must be reported;
the success rule below requires the economic advantage as well as a positive
NAV advantage.

| Item | Locked v1 choice |
|---|---|
| Development | 2021-01-01 through 2023-12-31; eligible regular sessions only |
| Validation | 2024-01-01 through 2024-12-31; no fitting on this period |
| Historical evaluation | 2025-01-01 through 2025-12-31; retrospective discovery |
| Confirmation | A separately admitted prospective period of 504 scheduled eligible sessions, with one final efficacy assessment |
| Primary arms | B versus R; separate original USD 10,000 accounts, initial B3 |
| Initial history | At least 253 completed sessions for common indicator eligibility |
| Observation | 126 completed return intervals after common eligibility, requiring 127 original closing NAV boundaries |
| Selector opportunities | Last completed eligible session of each calendar month; an accepted change executes at the next eligible open |
| First switch | After a full scored calendar month; the initial B3 installation is separately identified |
| Primary family pool | Existing fixed installed B3, B4 and B5, with exact source and parameter identities |

The date ranges select eligible venue sessions rather than inventing sessions
on every weekday. Warmup and observation are not scored returns. Historical
2025 results remain discovery evidence even if a frozen model produces a
positive result: present-day model knowledge and prior human or agent access
cannot be erased by calling that interval a holdout.

The prospective start, exact scheduled end, source rights, exposure inventory
and access controls must be fixed before that separate run. Missing sessions
are not replaced by extending the period after seeing performance. A declared
safety stop may end execution early, but does not create an early efficacy
success. The 504-session choice is an operating horizon, not a claim of
adequate statistical power for a small edge.

## 2. Universe, account authority and reference portfolios

The intended universe is frozen to these twelve research instruments:
**VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD and GLD**.
Their security/listing identities, venue support, inception coverage,
corporate actions, raw prices, analytical return adjustments, availability
cutoffs and permitted research use still require actual source qualification.
Tickers alone are not an admitted historical dataset.

The default v1 research mandate is long-only, whole shares, no leverage,
100% maximum gross exposure, 20% per ETF, 70% aggregate equities, 75% aggregate
bonds and 20% gold. There are no invented minimum class allocations. These
numbers are explicit design choices and must undergo the original mandate
feasibility review required by G3. A candidate that violates the mandate is
rejected; its weights are not silently projected into another strategy.

The per-transition turnover ceiling is 2.0 gross traded notional divided by
pretrade NAV, counting buys and sells. For a long-only unlevered portfolio,
moving all capital between disjoint holdings can require two NAVs of gross
trades. This ceiling preserves such transitions; it is not an empirically
calibrated monthly turnover limit. All internal, selector-switch and
protective-correction turnover must still be reported separately and in total.

Current-book drift beyond a cap is handled by the deterministic protective
correction policy in [the execution extension contract](contracts/stage1-execution-extensions.md).
It is independent of AI permission. It uses original prices, fees and
whole-share accounting; it sells only what is needed, retains resulting cash,
and never invents fills or redistributes proceeds into another asset.
Unknown execution state remains contained. A policy-compliant protective
correction is an observed event; an unauthorized risk override is a violation.

There are three original counterfactual reference books, one for each family.
They use independently allocated engine-created capital and the original
evaluator, accounting kernel, M0 invocation and retained RESULT. Their gains
never enter B's or R's cash. The reference adapter has explicit warmup-one
engine scheduling so that B5's first possible valid decision is session 61
and B4's is session 253. It holds existing quantities while an indicator is
unavailable, records that unavailability, and excludes those cash-only warmup
marks from eligible reference history.

B3 uses month ends from the admitted calendar. B4 and B5 retain their installed
daily decision rules. Monthly selector opportunities do not turn their
internal trading into monthly trading. References preserve the actual fixed
baseline behavior and its costs; current-account mandate eligibility is a
separate check when a selector proposes installing a family. Historical
admission must verify the exact analytical adjustment inputs supplied to
those installed families, including corporate-action treatment.

At a decision cutoff, the common context contains the latest completed 126
intervals from 127 original NAV marks, per-family availability, actual internal
costs and turnover, and causal trace-prefix evidence. It contains no later
mark, later terminal classification or final account value. B and R receive
detached copies of the same eligible common value. The original account,
RESULT and ledger locators remain auditable outside that candidate-facing
view. Missing histories are unavailable, not zero-return observations.

## 3. Deterministic comparator R

R is Drift's specified numerical heuristic, following methodology section
7.2. The method papers cited below support the uncertainty procedure, not the
choice of this portfolio objective or its coefficients.

For each currently eligible family, define:

\[
U_s = G_s - \lambda_v\sqrt{126}\,\widehat\sigma_s
      - \lambda_d |\operatorname{MDD}_s| - C_s.
\]

`G_s` is compounded net return across the 126 completed reference intervals.
`sigma_s` is the sample standard deviation of those daily net returns, using
denominator 125. `MDD_s` is maximum peak-to-trough drawdown from all 127 NAV
boundaries, including the initial boundary. These are fractional-return
units, not percentages or dollars. Zero return variance is valid; there is
no division by volatility. This sample-volatility feature is distinct from
B5's installed population-variance ranking over its 60 analytical returns.
Use the existing pinned 34-digit, half-even Decimal context for the score,
square root and comparisons; the executable adapter must retain the resulting
score components instead of introducing an unrecorded float tolerance.

`C_s` is the deterministic estimated transition cost divided by the active
account's decision-close NAV. The estimate uses the current original shares,
cash and pending claims, causal decision-close prices, the fixed family's
whole-share target and the frozen cost model. It cannot use the next open's
realized price. The coefficient of `C_s` is exactly 1. Staying in a family
does not imply zero cost if its actual scheduled internal rebalance would
trade. Reference returns already include internal realized trading costs;
those costs are not subtracted a second time from `G_s`.

Choose the greatest valid utility. Exact utility ties prefer the currently
installed family if it is eligible, then B3, B4 and B5 in that order. This
requires an explicit incumbent-aware adapter; modifying a score by a tiny
epsilon or relying on the generic selector's existing approximate tie rule
does not implement this policy. An unavailable metric, target, transition
estimate or current execution state cannot be replaced with a favorable zero.

### Development-only coefficient calibration

Freeze the nine ordered pairs in `{0.25, 0.5, 1.0} x {0.25, 0.5, 1.0}` for
`(lambda_v, lambda_d)`. Run every pair through one uninterrupted 2021-2023
development account, starting from independent USD 10,000 and B3 after the
same qualified warmup and observation rules. Do not reset capital at year
boundaries. Calendar-year results are diagnostics, not additional fitting
objectives.

Rank completed valid development runs by terminal net return, then smaller
absolute maximum drawdown, then lower total gross turnover, then ascending
numeric coefficient pair. Retain every attempted pair, refusal, incomplete
run, configuration, cost and original result. A missing required grid run
blocks the fitted artifact; it does not silently shrink the search to the
runs that happened to succeed. Neither validation nor 2025 outcomes may
select coefficients. The fitted pair is still missing until these actual
development executions and their immutable ranking proof exist.

## 4. AI method, information and operating costs

B uses one immutable model deployment, one versioned system/prompt/tool
configuration, the same fixed family registry, and pinned decoding, context,
budget, deadline and retry policies. A marketing model name is insufficient:
retain the actual provider revision/deployment identity, source availability,
complete requests and responses, tool inputs, output validation and replay
receipts. A provider that cannot supply the required identity remains an
unavailable dependency. This document does not select a fictitious immutable
revision or authorize paid model calls.

Model weights remain fixed. B may update its own time-eligible memory and
reflections using completed own-arm decisions and the shared reference
history. Original observations and failed attempts are immutable. Reflections
are versioned hypotheses, with corrections or supersession recorded; they
cannot overwrite the original facts. R receives equivalent eligible market,
reference and own-account information. Neither arm sees the other's private
actual-account feedback or a comparative scoring leaderboard during the run.

The primary retry rule permits one identical transport retry after a retryable
transport failure, within the same original deadline and monetary budget.
Malformed, invalid, abstaining or merely unpersuasive model content is a
completed attempt with its original disposition, not permission to keep
sampling until a preferred proposal appears. Every request, retry, timeout,
invalid response, refusal and abandoned configuration is retained and charged
according to the same frozen cost policy. Replay tests reproducibility; it
does not provide another independent investment observation.

Trading fees and slippage are booked once by the original account kernel.
Economic reporting then subtracts attributable incremental research and
operating costs outside NAV once, without creating a second cash ledger.
Unknown cost is not zero. Shared and one-time cost allocation, including the
development calibration search, must be frozen before comparison. Report
both recurring deployment cost and full attributable experiment cost, so a
positive operating result cannot conceal an expensive discarded search.
Synthetic one-basis-point fixtures do not establish a historical cost model.

## 5. Uncertainty procedure and materiality

The primary uncertainty procedure is a **paired stationary bootstrap** with
10,000 replicates, seed 575, and a two-sided 95% percentile interval. Each
replicate uses the same resampled session indices for B and R, compounds each
arm's sampled net returns separately, and calculates both their primary
terminal net-return difference and the corresponding economic difference.
Additive daily log-return or return-difference approximations do
not replace this terminal calculation. Attributable variable daily operating
costs follow the same paired indices; predetermined one-time allocations are
applied once per replicate.

Stationary bootstrap blocks have geometric random lengths and wrap around
the observed sequence. This retains local serial dependence under the
method's stationary, weak-dependence assumptions; it does not establish those
assumptions for a changing market or a learning selector. See the original
[Politis and Romano stationary-bootstrap method](https://doi.org/10.1080/01621459.1994.10476870)
and [the authors' Stanford technical-report page](https://statistics.stanford.edu/technical-reports/stationary-bootstrap).

The primary mean block length uses the corrected automatic stationary-block
procedure of [Politis and White (2004)](https://public.econ.duke.edu/~ap172/Politis_White_2004.pdf)
with [Patton, Politis and White's 2009 correction](https://doi.org/10.1080/07474930802459016).
The reference implementation is the `stationary` output column (internal
`b_sb` calculation) in [arch 8.0.0's source](https://bashtage.github.io/arch/_modules/arch/bootstrap/base.html).
Apply it separately to B returns, R returns and their difference; use the
ceiling of the largest finite result, bounded below by one. This aggregation
rule is a Drift design choice. Constant or otherwise undefined inputs carry
explicit diagnostics; they are not silently assigned an apparently validated
dependence estimate. Also report the preregistered 21-, 42- and 63-session
mean-block sensitivities. None may replace the primary interval because its
answer looks better.

The bootstrap implementation must retain its exact code/environment hash,
RNG algorithm/state, ordered input hash, selected block length and all
replicate indices or their reproducible stream plus digest. Use linear
interpolation at probabilities 0.025 and 0.975 over the ordered 10,000
replicate statistics, with zero-based position `(9999 * p)`. Do not report a
raw bootstrap sign frequency as a calibrated hypothesis-test p-value.
If an implementation cannot reproduce this definition, uncertainty is
unavailable until that implementation is reviewed and fixed.

Use one private `random.Random(575)` from pinned CPython 3.14.6 for the full
replicate stream. At each replicate's start draw `randrange(n)`. For each
following position, draw `random()` and restart with `randrange(n)` if the
draw is below `1 / b`; otherwise advance the current index circularly by one.
Stop after exactly `n` indices. Python documents this generator and explicit
state capture in its [standard-library random reference](https://docs.python.org/3.14/library/random.html).
The pinned interpreter and retained stream digest are required; the current
documentation page is not permission to change the runtime version.

There is one primary B-minus-R contrast. Other arms, windows, seeds, models,
cost assumptions and feature variants remain separately identified. A family
of confirmatory secondary hypothesis tests must use Holm correction over its
entire preregistered family; exploratory discoveries require fresh validation.
Report session count, monthly decision-opportunity count and realized number
of switches separately. A thousand captured-response replays do not increase
any of those independent investment counts.

The materiality threshold is **1% of initial capital per 252 scheduled
sessions**, after attributable incremental operating cost. For USD 10,000,
that is USD 100 over 252 sessions or USD 200 over the 504-session confirmation
horizon. Scale by the frozen scheduled horizon, not by the number of favorable
completed observations. This is a practical reporting threshold, not a claim
about investor preferences or a prediction-based switching hurdle.

Confirmation also requires B's annualized realized volatility to be at most
1.10 times R's and B's absolute maximum drawdown to be no more than R's plus
0.02. If R volatility is zero, only zero B volatility meets the ratio rule.
These risk-comparability bounds are explicit research choices, not validated
universal risk standards. Report both risk measures even when the economic
result is negative. A narrow bootstrap interval from one historical year
does not override the prospective-confirmation requirement.

## 6. Complete outcome precedence

Apply these rules in order to an actually executed run. An unadmitted design
has readiness `BLOCKED`; it is not a fabricated unsuccessful experiment.

| Priority | Outcome | Rule |
|---|---|---|
| 1 | `INVALID` | Known lookahead, unauthorized policy override, manipulated original evidence, unrecorded outcome-driven selection, or a violated frozen comparison rule |
| 2 | `UNAVAILABLE` | Required original account, execution, source, cost or comparable endpoint evidence is missing or contradictory, so the primary economic comparison cannot be established |
| 3 | `UNSUCCESSFUL` | Complete valid comparable evidence establishes B-minus-R net economic value at or below zero |
| 4 | `SUCCESS` | Positive economic value meets materiality, both the primary NAV and corresponding economic uncertainty intervals are strictly above zero, risk bounds hold, the separate prospective study is complete, and required independent acceptance is verified |
| 5 | `PROMISING_BUT_INCONCLUSIVE` | Positive valid economic value exists, but one or more materiality, uncertainty, risk-comparability or prospective-confirmation requirements are unmet |

An undefined uncertainty calculation does not erase a known negative economic
result. For a positive result it prevents success and must have an explicit
reason. `SAFETY_TERMINATED`, execution partiality and missingness are separate
reported attributes; they do not override the precedence table. A partial
execution retains its actual filled book and costs and cannot become a
completed strategy installation or completed learning outcome.

Late provider or operating-cost evidence creates a new as-of interpretation
with its own evidence tip. The original result, previously visible context
and original outcome classification remain immutable and auditable.

## 7. Typed calibration and admission deliverables

These are required contents of immutable artifacts, not claims that their
values have already been obtained. Existing original-receipt verification
must bind each artifact to the exact campaign, source and configuration.

| Artifact | Mandatory typed contents and checks |
|---|---|
| Reference history | Family/version/source identity; independent original allocation, M0 and RESULT references; exact calendar/universe/cost identities; cutoff; first eligible index; 127 marks and 126 contiguous intervals; original costs/turnover; unavailable reasons; prefix digest |
| R calibration | Nine ordered coefficient pairs; development dates; original account/result for every attempt; complete cost/status inventory; exact return/drawdown/turnover ranking inputs; selected pair; tie proof; completion time before validation access |
| Candidate transition | Active original account/state identity; fixed-family whole-share targets; causal price cutoff; fee/slippage policy; NAV-denominated estimate; actual mandate verdict; explicit unavailable reasons |
| Mandate feasibility | Exact security/class mapping; strategy source and calendar; every family/checkpoint's real target, whole-share result, refusal, correction and turnover; next-open gap checks; counts of eligible alternatives; original review |
| Historical costs | Dated source identities and permitted use; per-instrument units and coefficients; calibration interval; fee/slippage treatment; shared/one-time allocation; retry/search accounting; missingness policy |
| Model binding | Actual immutable provider/deployment revision; prompt/tools/context/feedback versions; decoding and seed policy; budget/deadline/retry policy; complete requests/responses; original replay evidence |
| Uncertainty execution | Exact paired original return/cost inputs and endpoint reconciliation; method/code/environment/RNG identities; session/opportunity counts; block-selection diagnostics; 10,000 replicate stream digest; primary interval and every sensitivity; undefined reasons and multiplicity inventory |
| Holdout audit | Human/agent/model access history; retrospective versus prospective mode; exact frozen prospective interval; original access-control and independent-audit evidence |

The existing G3 admission roles remain `g2_integration`, `dataset_qualification`,
`mandate_review`, `comparator_review`, `cost_review`, `model_replay`,
`scientific_protocol_review` and `holdout_audit`. Their receipts must be read
from independently configured original authorities. A receipt cannot choose
its own authority root, and local test evidence does not become independent
acceptance by changing a label.

The configured candidate accompanying this protocol may contain these locked
choices and missing-field diagnostics. It must leave actual dataset/model
identities, fitted values, artifact hashes and unreceived approvals absent.
Only `freeze_study` with complete verified inputs produces an admitted frozen
study; `verify_frozen_study` must still recheck that evidence before execution.

The [configured protocol candidate](../../../tests/fixtures/stage1/study-protocol-candidate-v1.json)
contains the valid existing `Stage1StudyDraftV1`, these explicit policy
definitions, hashes of their actual embedded content, the captured installed
source inventory, and the exact readiness result. Its `BLOCKED` status is
intentional. A policy-content hash identifies a written rule; it is not a
missing empirical result, model binding or independent review receipt.
