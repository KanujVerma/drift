# EXEC: additive intraday and extended-session contract

Revision E3. Proposed documentation contract for [#379](https://github.com/KanujVerma/drift/issues/379).
Producer: Matthew. Required research-consumer review: Krish. Cost and RESULT
measurement consequences require Harsha's specific consumer acceptance.
This draft is neither an accepted wire API nor implemented execution capability.
Material timing, evidence, migration and safety choices require an authorized
independent ruling before runtime. No provider, broker, paper-account or capital
permission follows from this document, a passing test, or its eventual merge.

## 1. Accepted foundation and implemented limits

Read [D01-D17](../decisions.md), especially D04/D06/D07/D14/D17, the
[design](../design.md), [crosswalk](../requirements-crosswalk.md),
[workstreams](../../workstreams.md), [workflow](../../agent-workflow.md),
[ADR 0012](../../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md),
[ADR 0015](../../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
and [ADR 0016](../../../adr/0016-controlled-adaptive-research-with-versioned-execution.md).
The implementation evidence below is pinned to main
`5583f112dfb45b8f6e8bc652de1cc4334ef8a247`; decisions blob
`2604dbb34d4bedeb6888342f336d2e62dedd4513`.

- [EvaluationProtocolV1](../../../../src/drift/domain/evaluator_protocol.py)
  fixes `post_close_decision_next_open_execution` and `session_scope=regular`.
  [AtomicRebalanceEngine](../../../../src/drift/evaluator/execution.py) uses
  listing-bound unadjusted next-open prices and all-or-none portfolio commits.
  Its current RebalanceOutcomeV2 carries PortfolioStateV2; preservation includes
  every existing daily/accounting schema version, not only V1 records.
- [ShadowBroker](../../../../src/drift/shadow/broker.py) uses the daily cadence,
  [M12 V1 models](../../../../src/drift/domain/shadow_broker.py) and the existing
  [reconciler](../../../../src/drift/shadow/reconciler.py). These do not already
  establish an intraday partial-fill or limit-order queue model.
- [OrderIntentV1 and ExecutionReportV1](../../../../src/drift/domain/execution.py)
  are broker-neutral V1 records. Their status enum has no UNKNOWN and their
  fee defaults cannot represent every case of unknown cost honestly.
  The [router](../../../../src/drift/execution/router.py) and append-only
  [journal](../../../../src/drift/execution/journal.py) are reuse anchors, not
  proof of durable account-wide uncertainty enforcement.
- The [safety audit](../../execution-safety-audit.md) retains S1 risk-boundary
  limitations and Critical S3/S4 uncertainty defects. This document does not
  repair or waive them. [#411](https://github.com/KanujVerma/drift/issues/411)
  owns the uncertainty/attempt/hold/resumption contract; its independently
  AI-critiqued S4/P4 remains proposed input, not an accepted runtime dependency.
- [The current clock](../../../../src/drift/evaluator/clock.py) refuses
  same-date multi-venue daily clocks. [#365](https://github.com/KanujVerma/drift/issues/365)
  owns authentic venue and multi-venue alignment changes. No MIC substitution,
  fabricated listing identity or silent weakening of that guard is permitted.

One provider-neutral evaluator and one authoritative account ledger serve all
arms. Extend accepted components through a reviewed adapter/timing boundary;
do not install a second simulator or treat the current daily engine as a
second-level matching engine. Exploratory evidence stays non-promotable under
ADR 0012; later qualification requires a new qualified run, not relabeling.

## 2. Proposed records and validation boundary

This proposal specifies semantic obligations. Names below are proposed record roles, not
new Python classes. The additive profile name proposed for review is
`drift-exec-intraday-v1`, schema version `1`, distinct from every existing V1
execution/evaluation profile. Freeze its canonical wire layout, validators,
hash inputs and golden examples only with the accepted producer contracts.
No caller may change EvaluationProtocolV1's literal to select this profile.

All references bind immutable record ID, version/profile and content hash;
hash equality alone authenticates neither source nor authority. Reuse existing
UUID7, SHA256Hash, FrozenModel, UTCDateTime and canonical serialization rules
where applicable. Quantities are nonnegative whole-share integers in this MVP;
requested quantity is strictly positive. Prices, monetary costs and seconds
use finite exact decimals, serialized without binary floating-point ambiguity;
currency, price basis and units are required. Use existing accounting precision
and rounding, not a new unreviewed monetary context. Do not add fractional
shares, leverage, shorting, options or crypto through this extension.

The future accepted layout must represent these required roles explicitly:

- Request: campaign/run/arm/account IDs, exact candidate/proposal revision,
  decision and input-cutoff references, source-version references, security and
  historical listing/venue IDs, side/quantity, order type/limit/TIF, intent hash
  and original client token, input-state version, mandate/approval/risk/eligibility
  references, timing/capability/fill/cost policy revisions and submission deadline.
- Timing trace: receipt/availability, review start/end, decision, approval,
  risk evaluation, submission start, modeled venue arrival, acknowledgement,
  fill and report-receipt observations, with evidence for each known stage.
- Capability evidence: dataset/source-resolution/rights references, account or
  simulated-environment identity, actual venue/session/order restrictions,
  validity interval, halt/quote/liquidity coverage and limitation reasons.
- Outcome: exact request and operation lineage, observation order/evidence,
  separately classified dispatch knowledge, lifecycle and accounting completeness;
  known cumulative executions and any bounded unknown fields, fill/effect
  references, open obligations, terminal evidence or explicit unresolved reason.
- Economic effect: immutable execution identity, quantity/price/currency,
  event/receipt times, fee components or explicit unknown reasons, source
  evidence and authoritative ledger posting/deduplication receipt.

Unknown, unavailable, not applicable and measured zero are distinct. A required
unknown leaf carries a reason and cannot pass the gate needing that fact.
Never fill a missing price/fee/quantity/time with zero, now, publication time
or a cached terminal state. Unsupported versions, invalid hashes, conflicting
identity, nonfinite values, negative durations, unrecognized status, incomplete
mandatory state or cross-arm evidence refuse dependent execution. Reject
unknown wire fields rather than quietly interpreting them as future capability.
Read-only evidence retention may continue under its own accepted permissions.

The exact minimal SRC definition belongs only to
[#394](https://github.com/KanujVerma/drift/issues/394). Broader SRC/RESULT belongs
to [#376](https://github.com/KanujVerma/drift/issues/376); source qualification
to [#378](https://github.com/KanujVerma/drift/issues/378); MANDATE/APPROVAL to
[#380](https://github.com/KanujVerma/drift/issues/380). Draft PRs
[#407](https://github.com/KanujVerma/drift/pull/407) and
[#408](https://github.com/KanujVerma/drift/pull/408) are input only. This proposal neither
defines a second SRC envelope nor accepts their drafts. Bind the accepted
revision of each affected producer contract before implementing its consumer.

## 3. Point-in-time admission and causal timeline

For every consumed version retain original publication/update time when known,
actual receipt, transformation availability and the accepted availability basis.
Never use the current corrected article or revised price as if its original
version had arrived earlier. A historical acquisition date is not automatically
the historical decision-availability time; reconstructed availability requires
an accepted source-specific policy and explicit limitation. If original-version
or availability evidence is missing, dependent historical claims are unavailable.
Public accessibility does not establish retention or replay rights.

The input cutoff admits only exact versions demonstrably available before the
decision snapshot, including any normalization/retrieval completion. New inputs
arriving during analysis are excluded or create a new immutable snapshot and
decision; they are not silently spliced into an already approved request.

Trace distinct events: source publication -> receipt -> normalized availability
-> review start -> review completion -> decision -> approval/risk validation
-> submission -> venue arrival -> eligible fill -> report receipt/posting.
Approval and risk checks may have their own observed ordering; both must be
valid for the final exact request/state at dispatch. Revalidate on changed
intent, mandate, state, price/capability or expired approval. A risk check is not
a replacement for trade authorization, nor is approval a substitute for risk.

Store UTC instants and source resolution/clock-domain uncertainty. An exchange
local date/session also carries its actual zone/calendar version; UTC date
alone does not identify that session. Evidence may bound an instant rather
than prove an exact instant. Do not manufacture ordering across overlapping
uncertainty intervals. Same-timestamp handling needs verified within-stream
sequence plus recorded causal processing order; a sorted UUID/hash or a
convenient global phase priority is not proof a quote followed submission.
Across incomparable streams choose the next provably eligible event or refuse.

Earliest admissible submission is after the latest proven completion of all
required input, analysis, authorization, risk and capability checks, within the
approved submission window. Use conservative upper time bounds where resolution
requires them. Add declared processing/transport latency before venue arrival;
the simulator cannot place an order into the market before it would arrive.
Earliest defensible fill is at or after that arrival and within a proven eligible
session, using the accepted fill rule's evidence. Equality requires verified
causal order; otherwise advance to later evidence. These are lower-bound
constraints, not promises that a fill exists at their maximum timestamp.

Missing measured latency may be represented only by an explicitly accepted
modeled assumption for a separately identified synthetic/exploratory run. Store
its policy, values, uncertainty and comparison role; never label it measured.
Do not optimize delays, data cutoffs or tie-breaks after seeing returns.

## 4. Sessions, quote freshness and execution capability

Capability is checked independently for source data, historical security/listing,
venue/session, order/fill model, simulated account, and any external account.
One supported dimension never supplies another. Model regular, pre-market and
after-hours as distinct capabilities. Full overnight remains out of scope until
separately verified and approved. No generic clock range or shared holiday list
certifies listing-specific trading, halts, early closes or overnight eligibility.

Use the genuine venue identity and point-in-time listing lifecycle. #365 must
accept multi-venue alignment before an affected SPY/IWM/QQQ cohort is enabled;
do not relabel NYSE Arca securities as Nasdaq or NYSE. Halt/suspension status
requires adequate time-eligible evidence for the claimed lane. A scheduled
session or missing halt record does not prove uninterrupted trading. Missing
necessary evidence yields unavailable/indeterminate execution, even in a run
otherwise labelled exploratory. A separately accepted sensitivity assumption
cannot be presented as an authentic observed execution.

Quotes bind security/listing, venue/feed, bid/ask, displayed size where needed,
event time, receipt time, sequence and evidence revision. At evaluation and
arrival they must satisfy the preregistered maximum age and feed-delay bounds,
spread/price consistency, session and market-state rules. Being older than the
decision alone does not invalidate a quote: a previously received quote can
remain usable only if the accepted freshness and validity rules still hold.
A pre-arrival quote cannot be reused as a guaranteed post-arrival fill without
evidence under the accepted validity/liquidity model. Stale or future-received
quotes fail; a bar close is not a substitute bid/ask. Unknown age or spread is
not zero. Quote freshness is necessary, not sufficient, for execution.

An accepted fill model specifies side-specific prices, marketable versus
nonmarketable limits, fees/slippage, queue/size participation, price/volume
resolution, auctions and halt/resumption behavior for each supported session.
A displayed quote, a crossed limit, a trade print or a bar high/low alone does
not prove this order filled. Marketability is not a guaranteed allocation.
Pre-market/after-hours simulation defaults to no capability, not to unrestricted
market orders; enable only explicitly accepted order/TIF/liquidity combinations.
Missing numerical limits or model policies block their dependent execution.

## 5. Outcomes, uncertainty and open obligations

Keep market eligibility, order lifecycle, dispatch knowledge and accounting
completeness separate. A locally refused request is not an authoritative broker
rejection. A confirmed rejection, a known unfilled expired/cancelled order,
an open acknowledged order and an unresolved submission are different facts.
Store modeled simulated outcomes as simulated, not broker-confirmed events.

Partial fills book only evidenced quantities and costs, retaining unresolved
leaves/open-order exposure. Do not mark a basket all filled because one leg
executed. Existing M2 all-or-none rebalance results cannot encode a partially
applied intraday basket; never construct a successful existing atomic outcome
of any schema version for it, including RebalanceOutcomeV2/PortfolioStateV2.
Intraday order/effect projection must feed the same accepted accounting kernel
through a separately reviewed boundary, preserving existing daily atomicity.

UNKNOWN describes missing knowledge, not a new favorable terminal lifecycle.
No default REJECTED, CANCELED, zero leaves, zero fee or flat account follows from
a timeout, empty lookup, lost report, process restart or unavailable feed.
The last confirmed report stays historical. Known fills may be retained while
remaining exposure or costs remain unresolved; incomplete RESULT cannot become
a clean performance claim. Unknown costs prevent a complete net-return claim.

Defer exact durable attempt, evidence-verifier, account-hold, restart, migration
and resumption bindings to the accepted #411 revision. This proposal requires their safety
properties without inventing a competing observer enum or storage protocol:
persist an operation before possible dispatch; preserve uncertainty after the
send boundary; prohibit duplicate placement and fresh-ID risk bypass; and refuse
new risk while relevant obligations are unresolved. A local refusal to cancel
does not clear its parent's uncertainty hold. Resolution/resumption requires
accepted independent authority, complete account/order evidence and effective
executor quiescence/fencing, not a timer or an empty readback.

Pause blocks new risk under #380; it neither cancels pending orders nor prevents
in-flight fills. A cancel is a distinct authorized operation. A cancel request,
failed acknowledgement or application shutdown cannot erase the order. Retain
late fills and cancellation uncertainty; permit only accepted bounded protective
actions/readbacks, with no implied liquidation or automatic resend.

Persist original intent/token, account/environment, operation lineage and exact
request hash. Repeated identical requests return the recorded observation or
perform a separately authorized readback, never a second placement. Reusing an
ID with changed content refuses. Account-scoped logical uniqueness and durable
guards must survive concurrency/restart; in-memory caches are not authority.
Missing broker order ID permits only readback supported by the accepted profile
using the original verified token; it does not invent broker lookup capability.

Deduplicate economic effects, not just notification UUIDs. Repeated cumulative
fills cannot be added as independent fills. Accepted atomic allocation must use
the last allocated frontier, including unacknowledged outbox effects, with
deduplication in the authoritative posting store. Corrections and later fee
adjustments retain lineage and accepted compensation rules. No second ledger
or reliance on an in-memory kernel proves durable exactly-once posting; #411's
actual settlement-store contract remains a prerequisite.

## 6. Costs, fallback and reproducibility

Record spread, adverse slippage, trading fees, order delays, partial/unfilled
opportunities and model limitations. Preserve M2's existing fee basis and
rounding for daily replay. An intraday fee/slippage policy receives its own
accepted revision and basis; do not silently apply daily open-price assumptions.
Do not count spread/slippage twice as both execution price and separate debit.
Keep trading-account cash effects distinct from inference/data/compute expenses;
bind raw operating-cost receipts and Harsha's accepted attribution policy.

Fallback is a preregistered policy with its own reason and comparison identity.
If intraday evidence is insufficient before any dispatch, record unavailable,
abstention or an explicitly permitted next-session fallback. A fallback decision
must rebind current state, inputs, mandate, deadline and approval. To use the
daily V1 protocol, form a proper post-close decision for its later-session open;
do not inject a 10:32 event into the old protocol or stamp an old decision later.
Next-session means the next genuinely eligible session, not the next civil day.

After possible dispatch, uncertainty must first be reconciled under the accepted
hold contract. A fallback is not another intent allowed to bypass it. Even an
undispatched request cannot silently roll a DAY order, expired approval or
stale quote into a later session. Preserve the original attempt and linkage.

For replay retain the exact source versions and rights basis, snapshots,
candidate and mandate revisions, timeline/order keys, policy profiles, accepted
capabilities, measured/modelled delays, evidence limitations, economic effects
and refusal/unknown records. Provider corrections append new versions; they do
not rewrite previous decisions. Campaign arms use the same accepted execution
rules and opportunity policy unless a declared comparison changes them.
Reproducible output is not proof of origin, authentic historical availability,
financial advantage, pristine holdout status or operational permission.

## 7. Additive versioning and migration

Keep every existing daily/accounting/execution model and schema version,
protocol literal, serializer, hash, fixture and historical row byte-identical.
This includes RebalanceOutcomeV2 and PortfolioStateV2 as well as V1 records.
No fixture regeneration, relaxed validator, source-grade
upgrade or interpreter/dependency change is part of #379. A new profile cannot
be deserialized as an existing daily/broker-report success merely because field
names resemble it.

Before runtime, accept the exact new wire types, version-dispatch rules and
consumer adapters. Inventory all active callers and persisted readers; upgrade
the affected boundary coherently or refuse its mutation path. Unsupported readers
may retain their old read-only histories but cannot dispatch via a legacy bypass.
Represent complete facts in existing record types only when lossless and
truthful; UNKNOWN, partial basket execution and missing costs must not be
flattened into false successes in any existing schema version.

Migration records accepted code/profile revisions, full legacy-history inventory,
append-only classifications of ambiguous histories, account bindings and replay
checks without rewriting source history. Align with #411's migration watermark
and old-writer exclusion. Golden replay across all existing schema versions and
the same accounting invariants are required before the new path is enabled.
No implementation, backfill or
private-state inventory is executed by this documentation task.

## 8. Synthetic acceptance examples

All times/prices/quantities below are invented fixtures, not market observations,
accepted production thresholds or evidence of provider/account access. Assume a
fixture-authorized regular session and valid policy unless its case denies one.
Display local times only with a fixture calendar/zone and retain UTC instants.

- A01, 10:32 announcement: publish 10:32:00; receive 10:32:03; normalize
  10:32:04; finish analysis 10:32:08; decide 10:32:09; approve/check risk by
  10:32:10; submit 10:32:11; modeled arrival 10:32:12. No earlier fill is allowed.
  A later valid quote still needs the accepted liquidity/allocation rule.
- A02, bar-only inputs: a 10:32 minute bar has favorable low/high but lacks
  within-minute order and executable size. Refuse an exact 10:32:12 fill and
  any touch-equals-fill claim. Retain unavailable or an accepted fallback.
- A03, late correction: original version received 10:32:03; corrected version
  received 10:40. A 10:33 decision cannot use the correction. If only corrected
  text survives, the original historical-information claim is unavailable.
- A04, after-hours limit: propose buy 100 at limit 100.00. The accepted fixture
  model supports only 20 shares at 99.99 and evidences their allocation. Book
  20 once with known fees; retain 80 unfilled/open as evidenced. No fill above
  the buy limit; missing session or size evidence yields no inferred fill.
- A05, halt: the scheduled session is open but the security is halted at arrival.
  Make no fill during the halt. Resume only on accepted resumption/liquidity
  evidence; absence of halt coverage cannot certify that a fill was possible.
- A06, quote older than decision: fixture maximum age is 2 seconds, not a
  production default. Quote time 10:32:05, decision 10:32:09, arrival 10:32:12
  fails. A quote from 10:32:08 received before the decision may serve the risk
  check if policy permits; it does not automatically remain valid for arrival.
- A07, timeout: submission may have executed; lookup fails or is empty. Preserve
  UNKNOWN and hold; same-token retry, fresh-ID request and next-session fallback
  cannot place again. No fabricated rejection, zero exposure or complete RESULT.
- A08, same timestamp: quote, decision and arrival all display 10:32:12 at
  coarse resolution. Verified causal sequence may establish eligibility; lexical
  ID sorting cannot. Without proof, advance to later evidence or refuse.
- A09, next-session fallback: no intraday capability, zero possible dispatch.
  Record the refusal and a separately permitted post-close decision/new binding;
  execute only at its next proven eligible open. An unresolved earlier order
  forbids this fallback; a weekend/holiday is not automatically a session.
- A10, duplicate/late fill: cumulative reports 5 then 10 allocate a total of
  10, not 15. Redelivery after posting/restart adds zero. A fill after a cancel
  request remains a fill. Unknown fee retains incomplete accounting even when
  quantity and price are confirmed; fee-only updates are not new share fills.
- A11, mixed venues: genuine ARCX and XNAS identities remain distinct. An
  unsupported ARCX representation or unaccepted multi-venue alignment refuses;
  relabeling to satisfy a single-venue clock is not a valid workaround.
- A12, compatibility and cross-arm binding: old golden daily input replays
  unchanged. New-profile UNKNOWN cannot enter an old success reader. A valid
  approval or account receipt from arm A cannot authorize arm B, and changed
  intent/state/expired approval fails revalidation without a replacement grant.

## 9. Acceptance map and remaining rulings

Issue criteria map to this document as follows: timeline/earliest execution and
source resolution in sections 2-3 (A01-A03/A08); sessions, limits, freshness,
halts and venue identity in section 4 (A04-A06/A11); partial/unfilled/unknown,
open orders and idempotency in section 5 (A04/A07/A10); latency/cost/fallback
and reproducibility in sections 3/6 (A01/A06/A09/A10); additive migration and
old replay in section 7 (A12). These are document examples, not executed tests.

Before runtime, Matthew must provide accepted revisions for timing/fill policy,
quote/source resolution, session and order capabilities, original-token evidence
and account settlement. #394/#376/#378/#380 and #365/#411 gate only their affected
bindings; their incompleteness does not prevent this independent proposal.
Polling limits, quote age/spread/size bounds, submission/approval expiry, latency,
queue/participation/fee policies and resumption authority have no guessed defaults.
An authorized independent ruling must accept material choices and identify the
trusted evidence/authority and settlement custodians. Krish accepts research
consumption; Harsha accepts affected measurement/cost implications. AI critique
and passing CI cannot supply those human/producer acceptances.

Document checks cover links/anchors, UTF-8/EOF, whitespace, fences, no U+2014,
acceptance mapping and exact sole-file scope, including the actual untracked file.
Future implementation requires separately authorized focused causal, partial-fill,
restart/concurrency, accounting and adversarial tests plus unchanged canonical
and hosted gates at the exact head. This task runs no product code or provider
probe. Claims/checks/heads/review receipts belong in GitHub, not a second live
status board here. Publication, merge/closure and operational activation each
require their own authority; no writer reservation is released by this draft.
