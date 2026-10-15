# UNKNOWN execution observation and reconciliation design

Revision: S4. Issue: [#411](https://github.com/KanujVerma/drift/issues/411).
Status: A1 direction approved by Matthew; this exact specification is a
proposal awaiting independent architecture review and an authorized ruling.
It is not a runtime, publication, broker or merge grant.

## 1. Scope, baseline and evidence

Baseline: main `6929b52136ec83b8291f26e2a82c2a1acf2b2d55`.
The [A1 proposal](https://github.com/KanujVerma/drift/issues/411) and
[docs writer claim](https://github.com/KanujVerma/drift/issues/411#issuecomment-6202158298)
identify Matthew, actor `matthew-philip`, writer
`Codex-DRIFT-411-A1-2026-10-15`, and the two-document write-set.

Read [AGENTS](../../../AGENTS.md), [onboarding](../../architecture/adaptive-experiments/onboarding.md),
[D01-D17](../../architecture/adaptive-experiments/decisions.md),
[design](../../architecture/adaptive-experiments/design.md),
[crosswalk](../../architecture/adaptive-experiments/requirements-crosswalk.md),
[workstreams](../../architecture/workstreams.md),
[workflow](../../architecture/agent-workflow.md), and ADRs
[0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md),
[0015](../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md),
[0016](../../adr/0016-controlled-adaptive-research-with-versioned-execution.md).
Their accepted intent is distinct from the new proposed interfaces below.

Current [Robinhood adapter](../../../src/drift/adapters/robinhood/adapter.py)
turns an unconfirmed submission error into `REJECTED`, defaults unfamiliar
raw statuses to `REJECTED`, and cannot establish cancellation success from
a failed transport. The [router](../../../src/drift/execution/router.py)
persists intents before dispatch but has no explicit durable uncertainty
state. The [journal](../../../src/drift/execution/journal.py) reads every
report as [ExecutionReportV1](../../../src/drift/domain/execution.py).
The [execution audit](../../architecture/execution-safety-audit.md) retains
S3/S4 and Decision Packet 2. Closed #363 and merged #364 were partial repairs.

The writer reproduced S4 with exact extracted methods and a synthetic timeout
transport in an in-memory Python harness. That diagnostic is not canonical
pytest, a real broker incident, source authentication or a runtime safety test.

This design addresses S3/S4 uncertainty and consumer handling. It does not
resolve S1 mandatory hard-risk enforcement, S5 portfolio completeness,
scientific promotion, provider entitlements, containment or operational access.
Those remain separately gated. #406 / DP-R1 is a different decision packet.

## 2. Required invariants

- R01: transport failure, empty lookup and unknown raw status never prove
  rejection, cancellation, zero fills, zero fees or zero exposure.
- R02: preserve V1 types, serialized bytes, profile constants, historical rows,
  hashes and append-only triggers. No fixture or interpreter/pin repair.
- R03: commit an immutable intent and unique logical operation reservation
  before I/O. Commit SEND_STARTED before permitting a transport invocation.
- R04: at most one initial submission invocation per account/intent/token,
  across workers, retries and process restarts. No automatic place-order retry.
- R05: pending dispatch and unresolved uncertainty durably block new risk for
  the affected account across all contexts, including a fresh intent ID.
- R06: uncertainty, reconciliation, settlement and resumption are separate,
  evidence-bearing transitions. No timer or cache clears a hold.
- R07: observed late fills survive pauses, cancellation failures and holds;
  cumulative reports cannot double-book a fill or fee.
- R08: bind account, environment, adapter, journal, intent and token. A digest,
  public model constructor or caller boolean is not authority.
- R09: all mutating entry points use the upgraded boundary or refuse. There
  is no legacy, direct-adapter or unconfined fallback.
- R10: unrecognized versions, incomplete migration, unavailable storage,
  ambiguous evidence and missing authorization refuse dependent dispatch.
- R11: model confirmed broker state separately from accounting completeness;
  missing measurements remain unavailable and never become favorable zeros.
- R12: this change supplies no broker, data, paper, live, spending or host
  permission. Offline component verification is not deployment readiness.

## 3. Chosen approach and alternatives

A1 adds a versioned observation envelope and append-only operation events.
Existing V1 reports remain evidence objects within that envelope. Adding
UNKNOWN to V1 would change its accepted value set without giving old readers
restart or migration semantics. Exception-only refusal lacks the requested
durable state and is not the selected architecture.

An UNKNOWN observation records what is not established; it is not a new claim
about the broker's own lifecycle. Confirmed rejection remains possible when
bound broker evidence actually establishes rejection. A local pre-dispatch
policy refusal is a separate NOT_SENT outcome, never a broker rejection.

## 4. Proposed domain and wire contracts

All new records use FrozenModel, UUID7 identifiers, timezone-aware UTC times,
canonical SHA256 hashes and explicit schema/profile discriminators. Models
are untrusted input until the trusted verifier validates them. Profile hashes
cover every field except their own hash, using repository canonical JSON.
Names and signatures here are proposed for the ruling; none exists yet.

New module: `src/drift/domain/execution_observation.py`.

- `ExecutionContextV2`: schema `2`, context_id, account_key, environment_id,
  adapter_id, journal_id, authority_policy_hash and context_hash. Each identity
  is nonblank or UUID7 as appropriate; account_key is the canonical registered
  broker/environment/account identity, not a display name or caller alias.
- `ExecutionAttemptV2`: schema `2`, attempt_id, context_hash, intent_id,
  intent_hash, client_token, operation (`submit`, `cancel`, `reconcile`),
  parent_attempt_id or None, expected_account_epoch, created_at, attempt_hash.
  Only a single logical submit root may exist for an account/intent/token.
  A new attempt UUID cannot create another logical submission root.
- `ExecutionEvidenceV2`: evidence_id, context_hash, attempt_hash,
  retained_receipt_ref, receipt_hash, verifier_profile_hash, observed_at,
  and evidence_hash. References point to authorized private retention, never
  copied secrets. Raw exception text is not a public evidence field.
- `BrokerStateFactV2`: schema `2`, fact_id, context_hash, intent_hash,
  client_token, broker_order_id or None, recognized ExecutionStatus,
  source_sequence or None, as_of, evidence_refs and fact_hash. Measurements
  cum_quantity, leaves_quantity, cum_gross_notional, cum_fee_amount,
  last_fill_price and avg_fill_price are individually nullable, with explicit
  missing_fields. Known amounts use
  Decimal and known quantities use nonnegative int. Values are populated only
  from verified source evidence; no field has a favorable numeric default.
- `ExecutionObservationV2`: schema `2`, profile
  `drift-execution-observation-v2`, observation_id, attempt_hash,
  account_sequence, previous_observation_hash or None, observed_at,
  knowledge (`CONFIRMED`, `UNKNOWN`, `NOT_SENT`), broker_fact or None, report or None,
  last_confirmed_report_hash or None, reason_code or None, evidence_refs,
  accounting_state (`complete`, `incomplete`, `not_applicable`), missing_fields,
  observation_hash. `report` is an exact ExecutionReportV1 payload.
- `ExecutionResolutionV2`: resolution_id, account_key, context_hash,
  expected_account_epoch, all_unresolved_attempt_hashes, observation_refs,
  open_orders_evidence_refs, account_reconciliation_ref, authority_ref,
  quiescence_proof_ref, resolved_at and resolution_hash. Lists are nonempty where required,
  unique and canonically ordered. Resolution covers a consistent account cut.
- `ExecutionResumeAuthorizationV2`: authorization_id, account_key,
  resolution_hash, expected_account_epoch, mandate_hash, authority_ref,
  expires_at and authorization_hash. Expiry and policy are required inputs;
  no duration, threshold or authorized human is supplied by this design.
- `ExecutionQuiescenceProofV2`: proof_id, account_key, journal_id,
  expected_account_epoch, covered_attempt_hashes, covered_executor_generations,
  effective_egress_fence_ref, authority_ref, verified_at and proof_hash.
  The verifier must establish effective quiescence/fencing, not accept the
  record because its constructor or hash validates.

UNKNOWN requires broker_fact=None, report=None, a nonempty uncertainty reason and evidence of
the attempted operation/error. It carries no current quantities or prices.
An optional last-confirmed report is explicitly historical, not an exposure
bound or substitute for reconciliation. NOT_SENT requires durable proof that
SEND_STARTED was never committed and no transport invocation was authorized.
CONFIRMED requires a verified, account/intent/token-bound BrokerStateFactV2 and
cannot accept an unfamiliar raw status by translating it to rejection.
Its V1 report is optional: it is embedded only when every V1 numeric field can
be populated truthfully. NOT_SENT has neither a broker fact nor a V1 report.

Proposed reason codes: `submission_unconfirmed`, `cancellation_unconfirmed`,
`response_unrecognized`, `evidence_conflict`, `recovery_required`,
`journal_unavailable`, `legacy_uncertainty`, `authorization_refused`.
Public reasons contain no account secrets or raw transport responses.

`accounting_state` is derived by the trusted verifier, never a caller success
flag. `missing_fields` names absent fill-quantity, fill-price, fee, timestamp
or settlement evidence. A V1 fee default of zero is not observed zero cost.
CONFIRMED/FILLED with incomplete fees is represented as a verified broker fact,
report=None and accounting_state=incomplete. It does not authorize cash
settlement or a complete RESULT. Exact verified fill quantities remain in the
fact. Missing fee does not make a recognized broker status unknown, and a
default-zero V1 payload is never constructed to carry it. UNKNOWN is used when
the broker outcome itself is not established. Historical V1 zero-default rows
are preserved as historical inputs and cannot be relabeled complete evidence.

## 5. Authority, account identity and capability boundaries

A trusted composition root registers one authoritative journal for each
canonical account/environment and binds adapter, verifier and authority
implementations. Registering a second context, path, copy or journal must not
reset that account's holds. Unknown registry identity or journal lineage refuses
dispatch. Multi-host or network-filesystem dispatch is out of scope and refused
until an independently accepted coordination mechanism exists.

Proposed policy protocols live in `src/drift/execution/authority.py`:

```python
class ExecutionEvidenceVerifierV2(Protocol):
    def verify(self, evidence: ExecutionEvidenceV2, *, context: ExecutionContextV2,
               intent: OrderIntentV1, attempt: ExecutionAttemptV2) -> VerifiedExecutionEvidenceV2: ...
    def verify_quiescence(self, proof: ExecutionQuiescenceProofV2,
                          *, context: ExecutionContextV2) -> VerifiedQuiescenceV2: ...
    def verify_resolution(self, resolution: ExecutionResolutionV2,
                          quiescence: VerifiedQuiescenceV2) -> VerifiedExecutionResolutionV2: ...

class ExecutionAuthorityV2(Protocol):
    def authorize(self, *, context: ExecutionContextV2, intent: OrderIntentV1,
                  operation: str, account_epoch: int) -> AuthorizationDecisionV2: ...
    def authorize_abandon(self, operation: RecordedOperationV2,
                          *, account_epoch: int) -> VerifiedLocalRefusalV2: ...
    def authorize_resume(self, resolution: ExecutionResolutionV2,
                         authorization: ExecutionResumeAuthorizationV2) -> VerifiedExecutionResumeV2: ...
```

VerifiedExecutionEvidenceV2 and DispatchAuthorizationV2 are verifier-issued
capabilities, not public wire records that authorize themselves. The verifier
checks source origin, receipt availability, exact binding, source sequence or
accepted ordering evidence, and field completeness under its accepted profile.
Wall-clock order or matching hashes alone cannot resolve conflicting evidence.
There is no permissive default authority or production verifier in this slice.
Offline tests use named fake authorities and transports with sockets disabled.

AuthorizationDecisionV2 is exactly DispatchAuthorizationV2 or
VerifiedLocalRefusalV2. A refusal binds issuer, attempt/request, account,
epoch and a bounded reason; it can record NOT_SENT without granting dispatch.
Authorization service failure leaves the PREPARED barrier intact and makes no
I/O; it is not silently treated as an issued refusal or successful grant.
VerifiedExecutionEvidenceV2 binds the verified input receipt to the operation,
optional broker fact/truthful V1 payload, completeness and accepted source
ordering. VerifiedExecutionResolutionV2 binds the resolution, evidence cut and
VerifiedQuiescenceV2; VerifiedExecutionResumeV2 binds accepted policy/authority,
resolution, current epoch, mandate and expiry. Each is internal issuer-owned
capability state, not a second freely constructible wire authority model.

The dispatch capability is an opaque, one-shot object issued by the registered
journal/coordinator for the exact operation. A model reconstructed from JSON,
a copied hash or an arbitrary Python object is rejected. Its consumption
performs the atomic SEND_STARTED transition and validates the current account
epoch, reservation and trusted binding immediately before I/O.

Python object discipline is not confinement against hostile code in the same
trusted process. Actual broker capability must remain absent until independent
containment and endpoint/tool enforcement prevent workers from bypassing the
trusted executor. #396/#397 and S1 remain operational blockers, not benefits
claimed for this state machine. No secret or host capability is inspected here.

## 6. Durable state and transaction boundary

Extend PersistentOrderIntentJournal in the same SQLite database with new
append-only tables: execution_contexts_v2, execution_attempts_v2,
execution_attempt_events_v2, execution_observations_v2,
execution_account_events_v2, execution_resolutions_v2,
execution_resume_authorizations_v2, execution_settlement_events_v2,
execution_settlement_allocations_v2 and execution_migration_events_v2.
Preserve existing tables and triggers.
Add no UPDATE/DELETE authority over evidence. Each new table has append-only
triggers, unique record IDs/hashes and verified foreign binding references.

BEGIN IMMEDIATE serializes account transitions. A transaction validates the
latest account epoch and unresolved set, then appends events with consecutive
account sequence and predecessor hashes. Projections may be rebuilt but are
not authoritative; missing, inconsistent or corrupt projection/evidence refuses.
The trusted registry prevents an alternative database from acting as authority.

Submission transitions:

1. PREPARED: atomically insert/reuse the identical V1 intent, create the unique
   logical submit root and account pending-dispatch event. Recording a request
   needs no dispatch grant. Authority then evaluates that recorded request;
   a verified refusal records NOT_SENT without inventing a dispatch grant.
2. SEND_STARTED: atomically consume the one-shot permit, recheck authority and
   account epoch, and record that dispatch may occur. Commit before transport.
3. OBSERVED_CONFIRMED or OBSERVED_UNKNOWN: atomically append evidence and
   observation, bind a confirmed V1 report where truthful, and append the
   matching account event. Unknown creates/retains a durable uncertainty hold.
4. RESOLVED: append independently verified resolution evidence. This does not
   itself grant resumption or erase any observation, hold or financial effect.
5. RESUMED: append accepted authority bound to the resolution, current epoch
   and mandate only after every relevant hold is resolved/reconciled.

A durable PREPARED reservation also blocks a different new-risk submission.
It can be abandoned as NOT_SENT only by an authorized transaction proving
that no SEND_STARTED exists and revoking every outstanding permit. Never
automatically retry an abandoned logical root or call it broker-rejected.

After SEND_STARTED any failure is potentially executed. A process killed
before the actual call still requires conservative reconciliation. If the
response arrives but the journal write fails, the prior event remains a
durable barrier. If storage cannot be read, no transport operation is allowed.
Restart scans all unfinished operations and holds before accepting new work.

At most one coordinator wins the logical submit reservation, and at most one
registered adapter invocation consumes a permit. Account pending/hold checks
and reservation insertion occur in one
transaction, not a separate read followed by an unsafe insert. No expiry or
process-liveness guess releases a reservation. A transport must not internally
retry a side-effecting request; the V2 wrapper rejects unverified retry behavior.

## 7. Reconciliation, cancellation and resumption

Reconciliation uses the original immutable intent, account and client token.
It never changes identity to make a retry look new. Empty, unavailable,
eventually consistent, partial or unbound lookup results remain UNKNOWN.
Only the accepted verifier can establish a confirmed broker outcome. An
intent not found once is not authoritative proof of non-receipt.

Cancellation is a separate operation rooted in the existing intent. It has
its own before-I/O record and one-shot permit. A request, acknowledgement or
transport exception is not confirmed CANCELED. UNKNOWN cancellation retains
last-confirmed lineage and observes fills that arrive afterward. Protective
cancel requests require explicit scoped authority; there is no automatic sell,
liquidation, replacement or new-risk exception to the account hold.

Read-only reconciliation may continue while an account is held, under bounded
accepted policy. Conflicts, lower cumulative quantities, regressed broker
sequence, mismatched identities or inconsistent amounts cannot reduce known
exposure or settle a contradictory report. Preserve them and keep the hold.
UNKNOWN is not a fabricated maximum-loss or worst-case valuation either.

Confirmed pending/partial states do not automatically clear an uncertainty
hold. Resolution covers every unresolved attempt at the same account epoch,
open-order commitments, late fills and account/book reconciliation. Relevant
measurement gaps are separately classified; a complete RESULT cannot consume
incomplete amounts. Resumption is independently authorized, expires under the
accepted policy, revalidates current mandate/state and does not override pause,
risk, source, capability or other emergency controls. An intervening event
changes the epoch and invalidates the prior resumption authorization.

Resolution also requires verified quiescence or effective egress fencing of
every executor generation that could invoke transport for a consumed permit.
A worker paused after SEND_STARTED but before the network call can otherwise
send after apparently clean readback and resumption. Revoking an unconsumed
permit, checking epoch once or seeing an empty snapshot does not close that
window. The proof binds account, journal, covered attempts/generations and
resolution epoch; an uncovered generation invalidates it. Missing proof retains
the hold. G3 must accept the actual enforcement/custodian; this document grants
no authority to terminate processes or change network policy. Quiescence alone
still cannot turn an eventually consistent empty lookup into a rejection.

## 8. Consumer and accounting boundary

Add BrokerAdapterProtocolV2 and ReconciledExecutionRouterV2 without silently
changing the V1 return type. V2 router methods return committed observations;
V2 adapter methods return evidence candidates that require verification and
receive bound operation permits. No external broker
mutation remains available through old V1 methods; they must refuse. V1 models,
builders, history reads and deterministic report replay remain supported.
V1 mutation refuses for every adapter, including mocks; positive mock execution
controls migrate to V2. No legacy mock configuration grants a fallback.

Migrate ShadowValidationEngine, CanaryExecutionOrchestrator,
CanarySettlementGrader and BoundedAutonomyOrchestrator explicitly to V2. Each
handles UNKNOWN/NOT_SENT before accessing a confirmed report. Unknown results
cannot mark an arm/account as clean, settled, ready or successful.

After unresolved execution, incomplete measurements or unverified final equity,
ShadowValidationEngine.finalize_summary raises IncompleteExecutionSummaryError
and persists no clean V1 summary. Caller-supplied final_equity or an empty
slippage list cannot manufacture successful zero slippage. A complete verified
session can use the existing summary schema without introducing a new type.

The existing one account ledger remains authoritative. An execution settlement
outbox records the verified cumulative fill/fee delta and its source evidence
with an idempotency key. Appending the outbox event and updating its durable
acknowledgement are separate append-only facts. The ledger consumer must dedupe
that key durably in the same transaction as the monetary/share posting. A
crash after posting but before acknowledgement must not post it twice. This
transactional receipt is a required consumer contract, not an assumed property
of today's canary grader. No second backtester or ledger is introduced.

Repository evidence matters here: today's canary grader checks broker cash
and emits a grade; it does not post an authoritative account ledger.
PortfolioAccountingKernel.apply_fill is in-memory and is not itself a durable
idempotency transaction. The proposed sink must therefore commit the unique
settlement key and authoritative financial effect together in the accepted
single account's durable store, then derive/rebuild the M2 kernel projection
from those committed facts. A crash in an in-memory projection is recovered
by fresh replay, not by applying the same fill to an already mutated kernel.
The ruling must select and bind that authoritative store and the initial
account-state receipt. No existing store is silently nominated here.

Proposed ExecutionSettlementSinkV2.post_once(effect: SettlementEffectV2)
returns SettlementReceiptV2. The effect binds account, intent, order, verified
fill/cumulative boundaries, exact quantity/notional/fee deltas and evidence.
The receipt binds the effect key/hash, account-store commit and resulting book
revision. Identical replay returns the same receipt; a different payload with
the same key refuses. This is an additional producer contract and release
blocker. A fake sink tests the outbox but cannot satisfy the production gate.
Rounded cumulative average prices are not exact cumulative gross notional;
missing decomposable amount/fee evidence keeps accounting incomplete.

SettlementEffectV2 and SettlementReceiptV2 are declared in the new domain module
before the journal uses them. The effect has effect_key, effect_hash,
account_key, intent_hash, broker_order_id, from_checkpoint_hash,
to_checkpoint_hash, kind (`fill`, `fee_adjustment`), quantity_delta,
gross_notional_delta, fee_delta, currency (`USD`) and evidence_refs.
Known quantities are nonnegative int and money is exact canonical Decimal;
fill effects require positive quantity. USD preserves the current account
kernel's supported currency; other currencies require a separate contract.
A receipt has effect_key/hash, account_key, store_commit_ref, book_revision
and receipt_hash. Its trust comes from the accepted store verifier/transaction,
not from a public receipt object. A fee_adjustment effect is usable only when
the accepted sink supports it; otherwise it remains held/unallocated.

The journal's observation-acceptance transaction reads the last **allocated**
quantity/exact-notional/fee frontier for the account/order, verifies the next
source checkpoint and derives the next non-overlapping effect. It appends the
observation, allocation/outbox effect and frontier transition atomically under
BEGIN IMMEDIATE. Pending and unacknowledged effects already count as allocated;
the sink acknowledgement is not the allocation frontier. A fresh observation
or report UUID cannot allocate the same economic interval again.

Effect identity binds canonical account, broker order and the verified from/to
cumulative checkpoint hashes, not an arbitrary new event UUID. Concurrent
0-to-5 and 0-to-10 observations must produce either 0-to-5 plus 5-to-10 or only
0-to-10, never overlapping 0-to-5 plus 0-to-10. Verified historical prefixes
allocate nothing; unorderable or conflicting evidence retains the hold.
Persist allocation/frontier facts in execution_settlement_allocations_v2.

Unchanged-quantity fee evidence cannot create another share fill. It requires
an accepted fee-adjustment effect/sink contract or stays explicitly unresolved
with an accounting hold; do not fabricate a zero-quantity PortfolioFillV1.
Unknown, negative or conflicting deltas cannot advance the allocated frontier
without an accepted corrective-effect contract. These rules apply even when
the prior monetary post succeeded but its outbox acknowledgement is missing.

Non-overlapping partial-fill deltas may be booked only from verified quantities,
prices and fee treatment. Reports are cumulative: repeated report IDs or an
unchanged cumulative quantity cannot produce duplicate fills. A decreased or
conflicting cumulative total is held for reconciliation. Unknown fees stay
unavailable; do not derive a zero fee from a V1 default, amend prior bytes or
claim complete cash reconciliation from incomplete measurements.

## 9. Migration and compatibility

The upgrade is offline and additive. Inventory the exact private journal scope
through an authorized custodian in a future operation; this task reads none.
Preserve all historical V1 rows, including misleading timeout REJECTED records.
Append migration classifications and holds for unconfirmed histories. Scan the
full history, not only the latest row, and treat incomplete inventory as a hold.
A later terminal row resolves earlier uncertainty only with verified binding
and adequate evidence. No text heuristic alone certifies an actual broker state.

Persist a completed migration watermark bound to the journal identity,
inventoried head/sequence and verifier profile. Every V2 open validates that
watermark and all later events before permitting dispatch. Unknown schemas,
unfinished migration, old-writer activity or corrupt rows refuse. Stop old
mutating writers before rollout; V1-only binaries must have no broker authority.
A copied journal or code rollback is not an authorized fallback.

Old payload bytes/hashes must remain identical. New implementation identities
may legitimately differ and require affected replay verification; this design
does not promise unchanged whole-source-tree fingerprints. Never regenerate a
fixture or adjust an expected hash to hide a mismatch. Isolate and classify any
unexpected replay change before proceeding.

## 10. Proposed API boundary for implementation planning

These exact signatures define the proposed plan inputs. All require the
trusted registered context and explicit authority/verifier implementations.

```python
class BrokerAdapterProtocolV2(Protocol):
    def submit_once(self, operation: RecordedOperationV2,
                    permit: DispatchPermitV2) -> ExecutionEvidenceV2: ...
    def cancel_once(self, operation: RecordedOperationV2,
                    permit: DispatchPermitV2) -> ExecutionEvidenceV2: ...
    def reconcile_once(self, operation: RecordedOperationV2,
                       permit: DispatchPermitV2) -> ExecutionEvidenceV2: ...

class ReconciledExecutionRouterV2:
    def submit(self, intent: OrderIntentV1) -> ExecutionObservationV2: ...
    def cancel(self, intent_id: UUID, authorization: DispatchAuthorizationV2) -> ExecutionObservationV2: ...
    def reconcile(self, attempt_id: UUID) -> ExecutionObservationV2: ...
    def resolve(self, resolution: ExecutionResolutionV2) -> None: ...
    def resume(self, authorization: ExecutionResumeAuthorizationV2) -> None: ...

class PersistentOrderIntentJournal:
    def record_request_v2(self, context: ExecutionContextV2, intent: OrderIntentV1,
                          operation: str, parent_attempt_id: UUID | None) -> ExecutionAttemptV2: ...
    def load_operation_v2(self, attempt_id: UUID) -> RecordedOperationV2: ...
    def issue_dispatch_permit_v2(self, attempt_id: UUID,
                                 authorization: DispatchAuthorizationV2) -> DispatchPermitV2: ...
    def consume_dispatch_permit_v2(self, permit: DispatchPermitV2) -> None: ...
    def record_not_sent_v2(self, attempt_id: UUID,
                           refusal: VerifiedLocalRefusalV2) -> ExecutionObservationV2: ...
    def record_observation_v2(self, verified: VerifiedExecutionEvidenceV2) -> ExecutionObservationV2: ...
    def account_state_v2(self, account_key: str) -> ExecutionAccountStateV2: ...
    def record_resolution_v2(self, verified: VerifiedExecutionResolutionV2) -> None: ...
    def record_resume_v2(self, verified: VerifiedExecutionResumeV2) -> None: ...
```

ExecutionAccountStateV2 is a replay-derived view of the authoritative account
epoch, pending operations, active holds, resolutions and mandate binding.
DispatchPermitV2 is internal, one-shot and not serializable as authority.
The coordinator owns identity verification and passes the issued, unconsumed
permit to the registered adapter. The adapter alone atomically consumes it
through the journal immediately before its one transport invocation; the
coordinator never consumes it. A caller cannot pass an arbitrary transport
into the journal or forge authority by providing a model.

RecordedOperationV2 is an immutable replay-derived view containing context,
original OrderIntentV1, current/root attempts, original client token, optional
verified broker order binding and latest observations/facts. load_operation_v2
rebuilds it from registered journal records after restart, without the
Robinhood adapter's in-memory intent/order maps. Missing or conflicting account,
environment, intent or original-token identity refuses. A missing broker order
ID does not prohibit original-token reconciliation under an accepted supported
readback contract; it does not establish provider support for such a lookup.
Cancel without a verified target supported by its accepted cancel profile
refuses before I/O. Callers cannot replace original tokens or intents while
rebuilding a cancel/readback request.
All operation strings above validate against submit/cancel/reconcile only.

End-to-end sequence:

1. The coordinator resolves the registered context and verifies migration,
   records PREPARED with record_request_v2, then asks ExecutionAuthorityV2 for
   the exact operation/current account epoch. No authority default is allowed.
2. A VerifiedLocalRefusalV2 goes to record_not_sent_v2. A successful grant goes
   to issue_dispatch_permit_v2, which binds the existing attempt and current
   epoch. A refusal or abandonment succeeds only before SEND_STARTED, revokes
   outstanding permits atomically and never erases the request.
   NOT_SENT describes that specific operation, not a parent order's lifecycle;
   a refused cancel/abandonment cannot clear an existing uncertainty hold.
3. The registered adapter consumes that exact permit through the journal
   before entering transport. Invalid, copied or reused permits make no I/O.
   The paused-worker window is handled by the quiescence/fencing requirement
   at resolution/resumption, not by claiming the local epoch check is atomic
   with a remote network send.
4. Adapter evidence candidates pass through ExecutionEvidenceVerifierV2.verify;
   only its capability enters record_observation_v2. The journal assigns the
   sequence/predecessor/hash and atomically allocates any valid settlement
   delta. A public observation model cannot bypass this boundary.
5. Restart, cancel and reconcile first use load_operation_v2. A cancel creates
   a separately authorized child attempt. A readback creates a bounded child
   reconcile attempt/permit using the original root binding; it never places
   an order. Failed readback is retained as evidence, not another risk-bearing
   broker obligation that must itself be resolved by endless future readback.
6. verify_quiescence and verify_resolution yield a bound resolution capability;
   record_resolution_v2 validates it against the live epoch and unresolved
   risk-bearing set. authorize_resume and record_resume_v2 separately require
   a current accepted grant. Neither accepts only the public wire records.

The coordinator constructor requires context, registered adapter/journal,
authority, evidence verifier, registry and settlement sink explicitly.
Verified capabilities are issued/validated by those registered implementations;
their exact production identities and fencing mechanism remain G3 prerequisites.

## 11. Acceptance cases and proof obligations

- A01: timeout after fake broker acceptance plus unavailable lookup creates
  UNKNOWN/hold, never a confirmed rejection or duplicate placement.
- A02: exact-token lookup proves the fill; one confirmed observation and one
  idempotent accounting effect, with all evidence retained.
- A03: empty/malformed/unknown-status/unbound lookup remains UNKNOWN; no
  invented quantities, prices, fee, cancellation or exposure.
- A04: same intent and fresh-ID new risk are refused during a hold, including
  aliases, a new context and an unregistered copied journal.
- A05: kill/reopen at every before/after-I/O and journal boundary preserves
  the barrier. A pre-commit failure makes zero transport calls.
  Restart with the original intent/token but no broker order ID permits only
  the accepted supported token readback, with the uncertainty hold intact.
  Also suspend a worker after consumed SEND_STARTED but before transport:
  resolution/resumption without verified quiescence/fencing must fail. Releasing
  that worker must not allow a send after a valid fence/resumption.
- A06: separate processes contend on SQLite; at most one initial placement.
  Reusing a permit or allocating a second attempt UUID cannot bypass it.
  Concurrent cumulative observations must allocate from the last allocated
  frontier, including effects whose sink acknowledgement is pending.
- A07: partial fill, cancellation timeout, pause and late fill retain lineage;
  the actual delta is booked once and UNKNOWN leaves stay unknown.
- A08: genuine rejection, local NOT_SENT and uncertain transport are distinct;
  unfamiliar raw statuses never default to rejection.
- A09: duplicate/out-of-order/conflicting/foreign-account evidence cannot
  reduce exposure, double-book costs or release the hold.
- A10: resolve/resume require the current epoch, complete evidence and accepted
  authority; expired/stale/forged grants and journal errors refuse.
- A11: legacy timeout histories stay byte-identical and receive append-only
  classifications; incomplete migration and old mutating readers cannot run.
- A12: positive controls for confirmed acceptance/fill/rejection/cancellation
  work with complete evidence and named offline authority; sockets and provider
  credential reads are forbidden throughout the tests.
- A13: confirmed status with missing fee/price stays accounting-incomplete;
  no zero-cost or clean-RESULT laundering, and an outbox replay after posting
  but before acknowledgement cannot duplicate an economic effect.
  A missing-fee fill has a CONFIRMED broker fact and no fabricated V1 report.
  Overlapping cumulative allocations and unchanged-quantity fee updates are
  tested separately; fee-only effects never masquerade as another share fill.
- A14: all direct/legacy entry points, hidden transport retries and resumed
  workers face the same durable guard or refuse before any transport call.
  A validation session with unresolved/incomplete evidence or unverified equity
  cannot emit a successful zero-slippage summary.

Proof requires focused RED/GREEN, process-level crash/concurrency tests,
adversarial binding/authority tests, consumer integration, unchanged V1 golden
payloads and the canonical repository gate. Future test results are not claimed.

## 12. Approval and implementation gates

G1: user approval of A1 direction is recorded. It does not accept this exact
wire/storage/permission contract. G2: independent review of the exact spec and
plan revision, with Critical/Important findings resolved. G3: an authorized
independent architecture ruling accepts or amends account hold, authority,
evidence, migration and settlement contracts, with named consumer acceptance.
G4: an approved exact runtime/test write-set, isolated writer claim, reviewed
implementation plan and accepted contract revisions. G5: offline verification
and independent implementation review. G6: separate publication/merge and
operational permissions. These gates cannot be collapsed into one green check.

Matthew is producer. Krish reviews research consumption. Harsha reviews
RESULT/cost/completeness implications; absent activation is not a blocker to
writing this proposal. A reviewer independent of the implementing agent must
give the authorized material ruling. Kanuj is not the mandatory global reviewer.
Fresh AI review provides independent critique, not human consumer acceptance.

Before runtime implementation, the ruling must name the trusted registry and
authority custodian, accepted broker evidence/ordering profile, polling and
expiry policy, legacy inventory scope and settlement consumer contract. Missing
values are deployment/contract blockers, not guessed production defaults.
The plan may build offline fixtures with explicit synthetic values only after
its own scope is approved. No provider, restoration, containment probe or broker
operation is part of this documentation task.
