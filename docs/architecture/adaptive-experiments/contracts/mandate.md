# MANDATE / APPROVAL: preferences and deterministic authorization

Revision M2. Proposed documentation contract for [#380](https://github.com/KanujVerma/drift/issues/380).
Producer: Matthew; required research-consumer review: Krish. Harsha reviews
affected campaign comparability, cost and RESULT implications. This proposal
does not accept numerical limits, implement a permission engine or enable an
account. Independent AI critique is not human consumer acceptance or an
authorized material safety ruling. Runtime and operations remain separately gated.

## 1. Foundation and implemented evidence

The accepted foundation is [D01-D17](../decisions.md), especially D04/D08/D14/D17,
the [design](../design.md), [crosswalk](../requirements-crosswalk.md),
[workstreams](../../workstreams.md), [workflow](../../agent-workflow.md),
[ADR 0012](../../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md),
[ADR 0015](../../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
and [ADR 0016](../../../adr/0016-controlled-adaptive-research-with-versioned-execution.md).
Implementation evidence is pinned to main
`5583f112dfb45b8f6e8bc652de1cc4334ef8a247`; decisions blob
`2604dbb34d4bedeb6888342f336d2e62dedd4513`.

[RiskPolicyV1](../../../../src/drift/domain/risk.py) contains order/position
notional and quantity limits, position weight, gross exposure, session/trailing
drawdown and order-rate fields. [HardRiskGatekeeper](../../../../src/drift/risk/gatekeeper.py)
consumes that policy and logs verdicts in the append-only
[risk journal](../../../../src/drift/risk/journal.py). These are reuse anchors,
not evidence that Ask/Smart/Auto, approval expiry or cross-process mandate
enforcement already exist. The gatekeeper caches an order's prior verdict;
portfolio-state checks are conditional and rate/peak state includes in-memory
values. The [router](../../../../src/drift/execution/router.py) and
[autonomy orchestrator](../../../../src/drift/autonomy/orchestrator.py) allow
optional risk-gatekeeper configuration. A cached verdict or an autonomy tier
does not prove fresh, state-bound approval for every dispatch.

The [safety audit](../../execution-safety-audit.md) retains known S1/S3/S4
limitations. This document neither repairs nor waives them. Preserve existing
risk/execution models, all V1/V2 accounting versions, profiles, hashes, golden
fixtures, append-only history and interpreter/dependency pins. No second risk
engine, account ledger, simulator, UI or broker adapter is introduced here.

## 2. Two independent policy layers

Conservative, Balanced, Aggressive and Advanced express authorized investment
preferences. They parameterize the same deterministic risk engine; they are
not four implementations or permissions to disable controls. Balanced is the
preregistered primary comparison under D08; other configurations are named
secondary conditions. Changes relevant to a campaign create a new policy or
campaign condition under its accepted study contract, never a silent rewrite.

Mandatory safeguards remain required in every mode/preset: trusted identity and
authority, complete current portfolio/open-order state, valid sources and market
capability, fresh prices, accepted policy and approval, non-levered permitted
assets/actions, loss/rate/exposure controls, durable dispatch uniqueness,
uncertainty holds, immutable audit and emergency controls. AI confidence and
human approval cannot override a failed safeguard. Larger tolerated investment
risk is not authority to bypass a source, identity, state or operational gate.

An effective policy is the intersection of the authorized mandate and separately
accepted system ceilings/floors. For maximum notional/quantity/exposure/loss/rate
budgets, the stricter compatible bound applies; missing or conflicting units,
scope or required values refuse evaluation. For required predicates, all must
pass. Do not use a generic numerical minimum for semantically different fields.
The system-policy custodian and permissible preference ranges require an
authorized ruling; a caller cannot nominate itself or hash a permissive policy
and thereby make it authoritative. There is no production fallback preset.

## 3. Proposed record roles and exact binding

These are semantic obligations, not existing classes or an accepted wire schema.
Freeze additive names/layouts/validators/hash inputs with the producer/consumer
contracts before implementation. Reuse FrozenModel, UUID7, UTCDateTime, SHA256Hash,
canonical serialization and existing money precision where appropriate. Amounts
are finite exact decimals with currency and basis; weights/drawdowns are integer
basis points (10000 = 100%); quantities are positive whole-share integers for
requests, nonnegative for known state. Times are UTC with resolution/clock
uncertainty and evidence. Unknown, missing, inapplicable and measured zero differ.

- Mandate revision binds issuer/custodian and verified grant evidence, immutable
  ID/version/hash, account/environment/campaign/arm, permitted universe and
  strategy-family revisions, actions, sessions/order types, effective risk policy,
  approval mode/Smart policy, budgets, activation/expiry, revocation/epoch and
  the accepted source, EXEC and scientific-eligibility profiles it requires.
- Approval request binds exact proposal/candidate revision, intent hash and
  original client token/logical operation, account/arm/environment, security and
  listing, side/quantity/order/limit/TIF/deadline, source/input cutoff, complete
  portfolio/open-orders/cash/reservations snapshot, prices/capabilities, mandate,
  risk/eligibility revisions and current authorization/uncertainty epochs.
- Approval decision binds that complete request hash, authenticated issuer and
  authority scope, manual or policy-derived basis, mode/policy revision, issue
  and expiry times, granted/refused reason and a nontransferable consumption
  identity. A source/content hash is integrity evidence, not issuer authentication.
- Enforcement receipt records current validated bindings, authorization/risk
  results, policy/state epochs, operation/attempt and durable dispatch receipt,
  plus explicit refusal or uncertainty. Keep logical operation identity distinct
  from notification UUIDs; a fresh record ID cannot create a second permission.

Required state includes authentic holdings and unmapped/unresolved assets,
cash/claims/liabilities and open/in-flight obligations, pending allocations,
appropriate marks/NAV, session-start and trailing peaks, rate/budget counters,
kill state, holds and exact evidence completeness. A missing snapshot, stale
view or quarantined holding is not an empty account. Do not allow a grant to
fill required unknown leaves with zero or to conceal unresolved exposure.

Before possible dispatch, revalidate the exact request against current authority,
state, source/price freshness, accepted risk/capability and eligibility. Fail
closed on unknown versions, incomplete identity/evidence, expired/revoked grants,
changed material bindings or unavailable durable state. A previous ALLOWED
RiskVerdictV1 is historical evidence, not reusable authority after state changes.
Manual approval of one binding never approves a modified quantity, price limit,
account, candidate or mandate. A policy-derived new grant may be issued only
after a fresh evaluation explicitly covered by the accepted mandate.

## 4. Ask, Smart and Auto

- Ask: an authenticated authorized human approves each exact request after all
  mandatory checks pass. Pending or declined approval makes no dispatch. Material
  binding changes invalidate that grant and require a fresh approved request.
- Smart: deterministic accepted predicates decide whether the exact valid request
  may receive a policy-derived grant or needs Ask. Every required value must be
  available and within the accepted bounds. Model confidence/sentiment alone is
  never a predicate substituting for measurable evidence. A request outside Smart
  bounds may ask only if it still passes mandate and all mandatory safeguards;
  a safety/mandate failure refuses rather than asking for an override.
- Auto: a trusted issuer derives a bounded, exact-request grant inside the
  previously authorized mandate after the same checks. Auto is normal for a
  frozen, separately permitted simulation campaign; it grants no arbitrary tools,
  model changes, external provider access or broker connectivity. Missing mode,
  mandate, accepted policy or verification never defaults to Auto.

Candidate Smart predicates, proposed only for offline fixtures/review, are all
ANDed: order notional <=500 USD and <=500 bps of current complete NAV; proposed
gross target-weight change <=100 bps of NAV; mark/quote age <=2 seconds; complete
state age <=5 seconds; spread <=10 bps; at most2 proposed new-risk orders in a
trailing60-second account window; all required cost/capability/eligibility leaves
known and all effective mandate limits satisfied. State/price tolerances are
measured at actual evaluation/dispatch boundaries, not a stale UI display.
These values are not approved thresholds or evidence that sources support them.

Define weights using the accepted complete NAV and explicit pre/post state,
with open-order reservations and all order legs included. Refuse nonpositive or
unknown NAV. The final Smart contract must define price basis, timing precision,
gross-change aggregation, counter treatment and every boundary comparison before
a campaign. Any missing policy prevents automatic qualification; it is not
silently treated as zero age, zero spread or zero costs.

Switching approval mode or editing a preset creates an authorized new mandate
revision. An adaptive proposer cannot change it itself. Existing accepted strategy
rules may act within their approved envelope without inventing new strategy
eligibility; changed strategy families still require their separate acceptance.

## 5. Numerical preset candidates, not accepted limits

The following illustrative values use a synthetic USD10000 account to make the
proposal reviewable. They are not investment advice, calibrated risk targets,
loss guarantees, production defaults or accepted campaign parameters. D08 leaves
numerical thresholds unresolved. The custodian and research/measurement reviewers
must accept an evidence-backed version before any dependent implementation/run.

Each candidate names all eight existing RiskPolicyV1 constraint fields:

- Conservative: max_order_notional500 USD; max_order_quantity5 shares;
  max_position_notional1000 USD; max_position_weight_basis_points1000;
  max_gross_exposure_basis_points6000; max_session_drawdown_basis_points100;
  max_trailing_drawdown_basis_points500; max_orders_per_minute1.
- Balanced: max_order_notional1000 USD; max_order_quantity10 shares;
  max_position_notional1500 USD; max_position_weight_basis_points1500;
  max_gross_exposure_basis_points8000; max_session_drawdown_basis_points200;
  max_trailing_drawdown_basis_points1000; max_orders_per_minute2.
- Aggressive: max_order_notional1500 USD; max_order_quantity15 shares;
  max_position_notional2000 USD; max_position_weight_basis_points2000;
  max_gross_exposure_basis_points10000; max_session_drawdown_basis_points300;
  max_trailing_drawdown_basis_points1500; max_orders_per_minute3.
- Advanced: explicitly supply every existing constraint field plus all new
  mandate/approval timing and budget fields, validated against accepted system
  bounds. Missing values refuse; selecting Advanced does not remove a control.

Order quantity and notional limits both apply, as do absolute position notional
and NAV-relative weight caps. They are not interchangeable. Currency conversion,
price/valuation and drawdown history must be accepted and complete. Proposed
caps cannot guarantee realized drawdown because gaps, slippage, delayed evidence
and existing obligations can exceed them. Drawdown trips halt new risk; they
do not imply an executable sale or a guaranteed stop-loss price. No leverage,
shorting or expanded asset class is enabled by the Aggressive name.

## 6. Expiry, revocation, atomic use and retries

Mandate, request and approval each have explicit validity windows; the earliest
applicable accepted deadline bounds use. An approval is valid only inside its
window and for its exact unrevoked bindings/current epochs. At equality with an
expiry/deadline it is expired unless the accepted contract explicitly defines
a different boundary; no undocumented grace interval or clock-skew allowance.
Conservative clock bounds must prove validity; uncertain ordering refuses use.

Missing/stale market or portfolio state, authority revocation, changed mandate,
candidate/intent/state or new uncertainty invalidates a previously evaluated
grant. Refreshing a screen or returning to Ask does not resurrect it. New grants
require the chosen mode's full reevaluation and evidence; preserve old receipts.

Reserve the exact request and required cash/exposure/rate budgets before possible
dispatch. Concurrent approvals/submissions must not both spend the same budget.
At the accepted dispatch boundary, atomically validate current epochs, allocate
the logical operation and consume its one-shot grant/permit. Crash/storage
failure cannot fall through to unjournaled I/O. Counter and budget state must
survive restart; creating a fresh worker/account alias cannot reset them.

Defer actual attempt, permit, account hold, readback and settlement storage
bindings to accepted [#411](https://github.com/KanujVerma/drift/issues/411).
One registered adapter invocation consumes an issued permit; this proposal does
not add a second competing consumption owner. After SEND_STARTED, any lost
outcome remains potentially executed and cannot be optimistically retried.
An identical logical request returns its recorded state or performs accepted
bounded readback, never a second placement. Changed content with reused identity
refuses; fresh-ID risk bypass also refuses during an account hold.

Revocation/hold races with an already consumed sender require #411's accepted
quiescence/effective egress-fencing proof before claiming safe resolution or
resumption. Checking a local epoch is not atomic with a network send. A paused
or crashed worker and empty broker readback do not establish that no send can
still occur. Do not promise that UI revocation recalls an in-flight operation.

## 7. Pause, protective actions and recovery

Pause means no newly authorized risk-taking dispatch. Persist the pause scope,
issuer, account/mandate/epoch and reason. Retain existing orders, reservations,
fills, costs and uncertainty; pause is not cancellation, liquidation or a flat
account. The kill-switch status labels in current V1 records are not renamed.

A protective action is a separate scoped operation under an accepted policy,
not an informal label bypassing checks. Prove its identity, quantity, target and
permitted effect against known complete state. A sell against unknown holdings
or a cancelled-order assumption can increase risk and is not automatically safe.
Permit only separately authorized cancel/readback or bounded protective execution
supported by accepted #411/#379 contracts; otherwise refuse and preserve the hold.
Cancelled/expired means evidenced lifecycle outcome, not an attempted request.

Retain fills arriving after pause/cancel/revocation, including costs and open
obligations. Unknown order state yields a local authorization refusal and durable
hold, not a fabricated broker REJECTED/CANCELED report. Book only verified effects
through the one authoritative ledger; incomplete costs/exposure keep RESULT
incomplete. A manual approver cannot clear missing evidence by assertion.

Recovery does not silently reset mandate, kill/pause/hold, peaks or counters.
Reference [#395](https://github.com/KanujVerma/drift/issues/395) for distinct
feature-off, isolated restoration and frozen-control evidence; this document
performs none of them. Restart reconstructs durable authoritative state or
refuses dependent dispatch. A copied/older database or new context is not a
fresh mandate. No private-state inspection or restoration is authorized here.

Resume requires the accepted custodian, verified relevant open-order/account
reconciliation, current mandate, complete evidence and independently authorized
scope/expiry bound to current epochs. Clearing a kill latch alone cannot clear
a separate pause or uncertainty hold. No timer, successful historical test,
policy-name change or switch to Auto authorizes resumption. Exact authority,
quiescence, evidence and storage contracts remain material ruling prerequisites.

## 8. Compatibility, source grades and acceptance examples

Reuse the existing risk and execution journals through an accepted additive
contract; do not rewrite old verdicts or weaken their unique/append-only guards.
An old verdict lacks the new complete binding and cannot be treated as a fresh
approval. Inventory all mutating callers/readers and coordinate version dispatch
before runtime; legacy bypasses must refuse, not fall back to optional checks.

[#379](https://github.com/KanujVerma/drift/issues/379) owns execution timing and
capabilities; [#376](https://github.com/KanujVerma/drift/issues/376) owns RESULT;
[#394](https://github.com/KanujVerma/drift/issues/394) alone owns the minimal SRC
envelope. Their proposed files/PRs are input, not accepted wire contracts.
Exploratory source evidence remains non-promotable. Data entitlement, scientific
eligibility, product approval mode, coding-agent authority and broker/paper/live
operation are separate grants. No Ask/Smart/Auto selection changes those facts.

All examples below are synthetic documentation cases, not executed tests:

- A01 changed proposal: approve buy5 at limit100 under candidate/version1;
  change to buy6 or a new candidate/state/limit. The old grant cannot dispatch;
  the chosen mode must produce a new exact-request grant after reevaluation.
- A02 stale prices/state: this fixture's mandatory freshness limits, separately
  from Smart routing limits, are2s for quotes and5s for state. Quote age3s or state
  age6s refuses automatic authorization. Manual approval does not cure the stale
  safeguard. A refreshed valid binding needs a fresh grant, not altered history.
- A03 revoked mandate: an unconsumed grant at epoch7 cannot dispatch after
  revocation/epoch8. A consumed sender requires fencing/reconciliation before
  a clean stop/resume claim; no suggestion that revocation undoes a real fill.
- A04 missing portfolio: holdings absent, quarantined security or unknown open
  orders is incomplete state, not zero exposure. Refuse new risk in all modes,
  including a claimed protective sale whose safe quantity cannot be established.
- A05 duplicate: two processes submit the identical logical intent/token. At
  most one placement and one budget reservation are possible; retry returns
  recorded state/readback. A fresh intent UUID cannot bypass an unresolved hold.
- A06 fill after pause: order acknowledged before pause fills2 afterward.
  Preserve the2-share effect/costs and remaining obligation; do not label it
  cancelled or reset portfolio state because the user paused new risk.
- A07 protective action: a separately authorized cancellation binds a known
  order. A failed/empty acknowledgement retains uncertainty; it does not clear
  the parent hold. Unknown target/capability refuses before I/O.
- A08 Smart boundary: at synthetic current NAV50000USD, a complete valid500USD
  request with100bps gross weight change meets the illustrative
  notional boundary;500.01USD requires Ask if still within the effective mandate.
  Any other Smart failure prevents automatic grant; a mandatory failure refuses.
  High AI confidence changes neither result. Concurrent requests share counters.
- A09 expiry/resume: grant expiry equals dispatch instant, or custodian/state
  proof is unavailable after restart. Refuse; changing preset/mode cannot revive
  it. Kill-clear with an outstanding account hold still cannot resume new risk.
- A10 preference intersection: candidate Aggressive permits10000bps gross but
  the accepted system ceiling is8000bps. A projected9000bps request refuses in
  every mode. Candidate caps remain unaccepted fixture values, not defaults.

## 9. Required decisions and document acceptance map

Matthew proposes the producer contract and numerical decision packet. Required
acceptance names exact effective policy bounds, trusted issuer/custodian, complete
state and authority verifiers, canonical binding/wire versions, age/spread/budget
rules, revocation/clock semantics, durable concurrency state and authorized
protective/resume profiles. Krish reviews research consumption; Harsha reviews
affected experimental comparability/cost measurement. Independent authorized
architecture review must resolve material policy/safety/storage choices before
dependent runtime, with no guessed production defaults or self-certification.

Issue criteria map as follows: safeguards/preferences and presets in sections2/5
(A10); exact binding/expiry/reapproval in3/6 (A01-A03/A09); unknown-state refusal
and measurable modes in3-4 (A02/A04/A08); idempotency/races in6 (A03/A05/A08);
pause/protective/in-flight/recovery/resume in7 (A06/A07/A09); evidence grades and
additive compatibility in8. D01-D17 remain accepted direction, not numerical
or runtime approval. No new Critical defect or empirical risk performance is
claimed by these synthetic cases.

Document validation covers local links/anchors, UTF-8/EOF, whitespace, fences,
no U+2014, criteria/examples and actual sole-file tracked/untracked scope.
Future implementation needs separately authorized focused/adversarial tests for
all cases, durable multi-process races/restarts and the unchanged canonical gate.
This task changes no runtime/test/schema/pin/fixture. Claims, exact revisions,
review receipts and actual CI results belong in GitHub, not a second status
database. Keep draft status and issue open until required acceptance and separately
authorized merge/closure; publication never supplies operational permission.
