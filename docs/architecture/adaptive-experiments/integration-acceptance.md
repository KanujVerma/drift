# Stage 1: First Auditable B-versus-R Integration Acceptance

## 1. Scope, authority and current state

This is the **design and independently executable acceptance specification** for
[issue #383](https://github.com/KanujVerma/drift/issues/383). Accountable
scientific owner: Kanuj under accepted ADR 0017. Prepared by ChatGPT using
GitHub publisher Krish-Verma under the user's issue-scoped direction. The
implementer is not the independent reviewer or the owner of Matthew's platform.

**State: REVIEW-READY DESIGN, NOT A COMPLETED INTEGRATED STUDY.**
The starting source revision is main
`0ec5e4bbb89488a49dfc438b2ad1420bc87e56ef`, after the independently
QA-accepted [K0-K5 integration #457](https://github.com/KanujVerma/drift/pull/457).
This document defines tests; it does not implement an evaluator, a second
ledger, an experiment orchestrator, or a real model call. It does not
approve historical data, numerical Balanced risk limits, model prompts,
confirmatory statistical thresholds or trading. Main and accepted contract
revisions must be rechecked before the first runtime integration issue.

The primary question remains the one stated in
[methodology.md](methodology.md): does an AI strategy selector B outperform a
competent conventional selector R in **paired net portfolio returns**, given
identical time-eligible information, risk mandate, available B3/B4/B5 choices,
and monthly decision opportunities? A correct negative, losing or incomplete
result is accepted as evidence; profitable synthetic fixtures are not.

**Two distinct executable levels must not be conflated:**

- **Level 0, fixture contract:** independent typed or retained mock source,
  decision, platform RESULT and research receipts verify identity, causal
  routing, arithmetic, abstention and completeness. No real fills, source
  qualification or retained history is asserted; supplied prices and mock
  RESULTs are separate witnesses.
- **Level 1, integrated synthetic campaign:** accepted Krish producer,
  Matthew's one authoritative evaluator/ledger/mandate/EXEC/RESULT, and Kanuj
  campaign/trial/metric/report components run a full controlled sequence with
  no duplicate simulator and no live provider. Starts **only** after the
  consumed exact revisions and owner/consumer reviews are accepted. An
  independently reviewed design document does not make that code exist.

## 2. Existing code to consume, not rewrite

| Owner | Actual source at integration base | Role and restriction |
|---|---|---|
| Krish | `src/drift/loop/stage1_switch_preflight.py` | Eligibility and completeness; an unavailable strategy does not create all-cash targets |
| Krish | `src/drift/intelligence/context_builder.py`, `validation.py`, `proposal_producer.py`, `conventional_selector.py`, `receipts.py`, `model_replay.py`, `learning.py` | Causal context, validated B/R proposals, offline attempts/costs and matured feedback; no broker |
| Krish | `src/drift/intelligence/platform_bridge.py` | Non-actionable typed proposal boundary, not Matthew's accepted M0 dispatch |
| Matthew | `src/drift/evaluator/`, `src/drift/ledger/`, `src/drift/risk/`, `src/drift/execution/` | Sole portfolio/result/position/cash/trading-cost authority; no parallel scientific ledger |
| Kanuj | `src/drift/experiments/stage1_campaign_config.py`, `stage1_trial_events.py`, `stage1_trial_provenance.py`, `stage1_metric_math.py` | Verified account/arm bindings, immutable trial evidence and pure metric arithmetic; no actual RESULT adapter inferred |
| Kanuj | `docs/architecture/adaptive-experiments/methodology.md`, `metric-contract.md`, `contracts/experiment.md`, `release-acceptance.md` | Published specifications, not frozen G3 thresholds or full producer-consumer acceptance |

The original B3, B4 and B5 strategy code and hashes stay frozen. Proposed
primary 12-ETF Stage 1 universe is
`VOO,IJH,IJR,QQQ,VEA,VWO,SHY,IEF,TLT,TIP,LQD,GLD`,
as specified in the current Stage 1 methodology and K0 preflight. It is
**not** the older SPY/IWM/EFA/etc. synthetic exploratory list. It remains
**unqualified** for real scoring until G1. B4 requires 253 completed sessions;
B5 requires 61, including 60 returns; a common first scored campaign waits
for 253 warmup + 126 observation sessions and fresh independent accounts.

### Version/contract gates at the time of this specification

- **Published scientific design:** #377 methodology, #382 metric contract,
  #392 EXPERIMENT/ELIGIBILITY and #397 release-acceptance specification.
  Their documents on main do not themselves freeze a scored G3 campaign.
- **Published offline research code:** merged #457 is tested for synthetic
  behavior, but the external research producer contract #375/#400 still
  needs exact consumer review and acceptance.
- **Open Matthew producer contracts:** #376/#407 SRC and RESULT, #379/#412
  EXEC/timing, #380/#414 MANDATE/APPROVAL and #423 M0 pre-staging
  switch-admission implementation. Their draft proposals are NOT accepted
  Python APIs or full integration permissions.
- **Scientific G1-G3:** provider/version availability, rights, qualified
  calendar and corporate actions, final Balanced numerical limits,
  method/model/prompt/seed/cost/holdout policy and confidence/power/stopping
  rules require independent accepted revisions. No values are guessed here.

These are exact blocking dependencies for **Level 1**, not excuses to delay
the separately supported Level 0 acceptance design.

## 3. Synthetic golden campaign: SYNTH-STAGE1A-BR-001

All following identifiers and values are **fixture-only** and NOT accepted
wire names, source receipts, portfolio fills, prices or market-return claims.

| Component | Fixed Level 0 value |
|---|---|
| Campaign/run | `SYNTH-CAMPAIGN-001` / `SYNTH-RUN-001` |
| Independent arms | `ARM-B` (AI), `ARM-R` (conventional), initially frozen B3 |
| Accounts | `ACC-SYNTH-B-001`, `ACC-SYNTH-R-001`; initial cash USD 10,000.00 each |
| Menu | Only fixed B3 equal-weight, B4 12-minus-1 momentum, B5 low-volatility |
| Unscored history | W001-W253 complete + O001-O126 complete; no return credited to scored accounts |
| Scored opportunities | First synthetic month S001-S021; no adaptive selector switch until S021 is complete |
| Decision cutoff | `2026-01-30T21:00:00Z` |
| Eligible source | `SRC-EARLY`, available `2026-01-30T20:59:59Z` |
| Late source | `SRC-LATE`, available `2026-01-30T21:00:01Z`; excluded from this decision |
| Decision finalized | `2026-01-30T21:00:05Z`; does not move the evidence cutoff |
| Next eligible synthetic open | `2026-02-02T14:30:00Z`; no same-close fill |
| B proposal | `PB-001`, current B3 -> B4, using `SRC-EARLY` |
| R proposal | `PR-001`, current B3 -> B3, using `SRC-EARLY` |
| Synthetic mandate | `PB-001 = PERMITTED_BY_MOCK`; `PR-001 = INCUMBENT_UNCHANGED_BY_MOCK` |
| Distinct price sentinels | VOO decision close 100.00 -> next open 101.00; IEF 50.00 -> 49.50 |
| Mock B RESULT | initial NAV 10000.00, gross gain 150.00, trading costs 30.00, terminal NAV 10120.00 |
| Mock R RESULT | initial NAV 10000.00, gross gain 80.00, trading costs 20.00, terminal NAV 10060.00 |
| Mock operating receipts | B 25.00 USD, R 5.00 USD; abbreviated fixture values, not valid full `raw_cost` records |

The examples above are consistent with the canonical
[implementation handoff](../implementation-handoff.md). This page may not
replace the final accepted `CampaignSpecV1`, `RunAccountBindingV1`,
`Stage1TrialEvent` or `Stage1TrialProvenanceSnapshotV1` with those
abbreviated literals. At Level 1, map to the existing implemented constructors
and independently verify the entire complete manifest and per-arm account
bindings rather than inventing new accounts from a missing declaration.

### Golden economic arithmetic

Use exact `Decimal` calculations, never floats for dollars.

| Quantity | B | R |
|---|---:|---:|
| Gross gain, USD | 150.00 | 80.00 |
| Platform trading costs already subtracted from NAV, USD | 30.00 | 20.00 |
| Net account gain, USD | 120.00 | 60.00 |
| Terminal net NAV, USD | 10120.00 | 10060.00 |
| Account return | 0.0120 (1.20%) | 0.0060 (0.60%) |
| Separately attributed research operations, USD | 25.00 | 5.00 |
| Economic gain after research operations, USD | 95.00 | 55.00 |

Expected paired account-return difference B minus R:
`(10120 - 10000)/10000 - (10060 - 10000)/10000 = 0.0060`,
or **0.60 percentage points**. Expected derived economic gain difference:
`(120-25)-(60-5) = 40.00 USD`.

Do not debit research compute a second time from account NAV. Do not infer
these mock gains from the two price sentinels: they are independent supplied
test witnesses. Positive fixture arithmetic is not investment advantage,
statistical significance or promotion eligibility.

## 4. Fixed causal end-to-end process and identities

1. **Verified campaign setup (Kanuj E1):** resolve exact campaign, run and arm
   fingerprints, accepted revisions, initial/account bindings, frozen B3
   family and separate study windows. Reject duplicate/missing B/R bindings,
   incomplete full manifest, swapped account, tampered hash or same account
   shared across arms. Immutable shared market bytes are allowed; mutable
   decisions/positions/attempt stores are not shared.
2. **Point-in-time evidence and reference histories (Matthew + Krish):**
   qualify every required B3/B4/B5 reference portfolio as a separate
   counterfactual account, using genuinely complete time-eligible history.
   Source publication is not local availability. Reject missing B4/B5
   prerequisites, feed gaps and future normalized data; no false sell-all.
3. **Monthly checkpoint and decision context (Krish):** only the published
   cutoff and mature own-arm feedback may enter B/R contexts. Every choice
   has a bound context/policy/source/method hash and explicit raw attempt/cost
   receipts. R is a genuine deterministic risk-aware competitor under its
   accepted scoring policy, NOT a deliberately weak fabricated baseline.
4. **Scientific pre-decision eligibility (Kanuj Phase A):** check the frozen
   B3/B4/B5 menu, required evidence and campaign/arm/ref versions. A
   missing or wrong-arm input refuses. Complete opportunity is distinct
   from completed valid attempt; all attempts are recorded.
5. **Risk and execution admission (Matthew Phase B):** authenticate current
   account positions/cash/open orders, risk policy and exact preflight
   verdict. An eligible B4 strategy switch is a proposal, not a fill.
   Invalid incumbent state requires indeterminate/containment, not an
   optimistic hold. Proposed missing history cannot become a liquidation.
6. **Next-open simulator execution (Matthew Phase C):** with accepted
   calendar/venue/market data, apply the selected frozen strategy's *full
   target portfolio* at the next eligible open, using the one existing
   evaluator and authoritative cash/position ledger. Permit accepted
   filled, partial, unfilled, rejected and unresolved/UNKNOWN outcomes.
   Never backdate a fill, silently treat pending orders as finished,
   fabricate order receipts or charge costs twice.
7. **Retention and completeness (Kanuj):** persist/replay bound
   `Stage1TrialEvent` and full `Stage1TrialProvenanceSnapshotV1` by
   campaign/run/arm/checkpoint; an omitted snapshot is
   `MISSING_SNAPSHOT`, NOT automatically observed empty. A true submitted
   empty trial remains distinguishable from absent evidence. Any missing
   authoritative RESULT stays `PENDING_RESULT` or equivalent accepted
   incomplete state; never create terminal NAV from a proposed strategy.
8. **Derived scientific reporting (Kanuj Phase D):** consume only verified
   Matthew RESULT and Krish operating receipts, preserve gross/net/economic
   columns and missing operating-cost state. Calculate the paired primary
   B/R measurement with separate reference controls; use the independently
   approved metric math and uncertainty method when actually eligible.
   Undefined Sharpe, incomplete trial and insufficient independent
   checkpoints are not successes. An independent reviewer signs the
   report-revision evidence, not an agent's own output.
9. **Replay and revocation:** replay from complete retained input, clocks,
   policy/strategy/fit, candidate, attempt, platform, research-cost and
   trial fingerprints. Mutated/removed evidence, changed approval, failed
   reconstruction or stale status invalidates dependent reporting.
   A replay of an already-consumed event does not duplicate fills or costs.

## 5. Deterministic acceptance and adversarial cases

At Level 0 these are table-driven **given records**. At Level 1 execute
against exact accepted producer adapters with real synthetic account state;
do not replace their tests with self-consistent mocks.

| ID | Input mutation relative to golden fixture | Required classification / invariant |
|---|---|---|
| INT-01 | Unmodified complete fixture | All causal/source, arm and math assertions; classified `SYNTHETIC_ONLY` |
| INT-02 | B candidate references `SRC-LATE` | `UNAVAILABLE`; candidate cannot consume post-cutoff evidence |
| INT-03 | Remove B selected strategy, forge candidate hash | `INVALID`; no mandate or target staging |
| INT-04 | Put ARM-R private feedback into ARM-B context | `INVALID`; no cross-arm leakage |
| INT-05 | Delete B platform RESULT | `PENDING_RESULT`; no invented B NAV or paired economic report |
| INT-06 | Change B research cost to unknown with explicit reason | Economic comparison `MISSING_COST` / `UNAVAILABLE`, but verified B account NAV remains reportable |
| INT-07 | Replay identical event/attempt/RESULT ID and bytes | One logical record; zero duplicated fills or research charges |
| INT-08 | Same event ID with different retained bytes | Conflicting duplicate rejected; original unchanged |
| INT-09 | Mandate refuses B4 transition | Zero transition orders; retain incumbent only if independently known valid |
| INT-10 | R selects existing B3 | No selector-level transition; ordinary B3 internal rebalances remain independent |
| INT-11 | Required B4 history only 252 sessions or B5 only 60 | `UNAVAILABLE` preflight; never an empty sell-all target |
| INT-12 | One of the 12 required ETF identities or sessions missing | Source/selection unavailable; no claimed full eligible universe |
| INT-13 | Replace qualified calendar with weekday/month-end heuristic | Refuse real-session qualification; synthetic checkpoint remains explicitly declared |
| INT-14 | Select at close and try fill at the same close | Refuse invalid execution causality; next-open only |
| INT-15 | Initial B and R accounts collide or swap | Rejected before an evaluator or report consumes them |
| INT-16 | Reuse B learning state in R or later matured trial at earlier cutoff | Reject cross-arm/future feedback; historical decisions immutable |
| INT-17 | Partial fill, pending cancel or unresolved/UNKNOWN order | Do not claim full target or terminal RESULT; reconcile actual positions/cash first |
| INT-18 | Account paused, stale mandate, unknown cash or existing breach | Refuse or require containment; no automatic safety-guaranteeing hold |
| INT-19 | Remove one checkpoint snapshot but leave the campaign manifest intact | `MISSING_SNAPSHOT` remains distinct from true `UNOBSERVED` |
| INT-20 | Self-rehashed source/portfolio/cost/record with mismatched nested identity | Fail closed; hash recomputation alone is not trusted authorization |
| INT-21 | Substitute B mock costs into R scientific attribution | Reject cross-arm attribution; portfolio NAV remains unchanged |
| INT-22 | Change one counterfactual portfolio result while keeping original AI NAV | Context/reference hash changes but AI NAV is not implicitly rewritten |
| INT-23 | Omit volatility/return series or zero-volatility period | Report `UNAVAILABLE`/`UNDEFINED` metric with no fabricated favorable zero |
| INT-24 | Report positive B-R difference with no G3/independent acceptance | `BLOCKED` scientific efficacy/release; golden fixture success is mechanical only |

Tests must include positive controls so the all-refused implementation cannot
pass by vacuity, and include independent hand-calculated values. Preserve
every failed, rejected, incomplete and discarded attempt with traceable reasons.

## 6. Reviewer trace and remaining real dependency gates

| Gate | Producer / reviewer | When it is satisfied |
|---|---|---|
| Identity, experiment contract and trial provenance | Kanuj, external scientific reviewer | Existing E1/trial implementations consume accepted contracts, frozen complete campaign and independent review of exact code |
| K0-K5 proposal/replay and costs | Krish, Matthew/Kanuj consumers | Merged #457 engineering proof is present; external research contract #375 must be independently accepted before wider producer integration |
| Source, calendar/venue and corporate actions | Matthew and source-rights reviewer | #376/#378 plus qualifying provider evidence, historical availability, allowed retention, admitted twelve-security universe |
| Next-open, partial/unfilled/UNKNOWN and pre-stage admission | Matthew, Krish consumer | #379 EXEC/RESULT and #423 actual admission guard reviewed; one evaluator, no second ledger |
| Numerical Balanced mandate, correction/containment | Matthew + Kanuj decision/reviewer | Accepted #380/DP risk limits and separately versioned correction policy, not current placeholder defaults |
| Study/metrics/frozen compare | Kanuj + unconflicted scientific reviewer | #377/#382/#392/#397 acceptance, G3 preregistration, enough eligible observations, complete trial accounting and score method |
| Historical scored evidence and forward readiness | Independent scientific review and owner release | G4 reproducibility after G1-G3, then independently authorized G5; no automatic G6 |

The workstream owners must record exact accepted revision receipts and
compatible provenance, not merely issue closure or a passing synthetic test.
No additional roles may self-certify their own missing science/platform
acceptance. The product can correctly reject or find no strategy advantage.

## 7. Next implementation issue and AntiGravity handoff

This one-file #383 deliverable is **complete as an independently reviewable
acceptance design**, but the Level 1 end-to-end execution is not implemented or
authorized by this issue. After the above exact producer contracts are
accepted, Kanuj should create a separately authorized integration issue
whose **proposed** isolated file scope starts with
`tests/integration/test_stage1_br_synthetic.py` plus explicitly approved
adapter paths owned by Matthew/Krish/Kanuj as required. That future issue must
use the mandatory fifteen-field implementation task format in
[implementation-handoff.md](../implementation-handoff.md).

AntiGravity should independently review this specification for alignment
with accepted stage decisions, correct B3/B4/B5 identity and account math,
non-vacuous negative tests, causal source and result separation, disjoint
producer ownership, versioned blockers and approved source limitations.
Run docs link/whitespace/U+2014 checks on the exact #383 PR. Neither
documentation review nor a synthetic-only status label is authority to
perform unapproved historical scoring or paper/live trade execution.
