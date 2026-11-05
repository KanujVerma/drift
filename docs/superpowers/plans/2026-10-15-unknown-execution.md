# UNKNOWN execution implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> for native task-by-task execution, or superpowers:subagent-driven-development
> only if the human explicitly selects that method. Steps use checkboxes.

**Goal:** Replace false terminal broker outcomes with durable, versioned UNKNOWN
observations, reconciliation holds and verified, idempotent consumer handling.

**Architecture:** Preserve V1 report bytes and add a V2 observation envelope,
append-only attempt/account events and a guarded V2 dispatch boundary. Replay
unfinished operations before dispatch; upgrade consumers together and refuse
legacy mutation. Account settlement requires an accepted single-store contract.

**Tech Stack:** Existing Python 3.14.6, Pydantic FrozenModel, SQLite, pytest,
Ruff, mypy and uv.lock; no new dependency or pin change.

**Spec:** [UNKNOWN execution design](../specs/2026-10-15-unknown-execution-design.md)
revision S4. [Issue #411](https://github.com/KanujVerma/drift/issues/411).
Baseline: `6929b52136ec83b8291f26e2a82c2a1acf2b2d55`.
Revision: P4. Proposed implementation plan, NOT execution authorization.

## Global constraints

- Runtime changes remain gated until exact architecture ruling, consumer
  contracts, plan and runtime write-set are approved and claimed.
- R01-R12 in the spec apply to every task. Existing V1 models/profile constants,
  rows, hashes, daily replay, source grades, .python-version and uv.lock stay
  unchanged. No fixture regeneration or hash changes to hide a failure.
- Use only named offline transports/authorities with sockets and provider
  credential reads forbidden. No external broker/provider/host/private-state
  action, merge, closure or production policy default is authorized.
- One authoritative journal per canonical account/environment; context aliases
  and copied journals cannot clear a hold. Hashes/models do not grant authority.
- Every planned path below is a candidate for a future exact write-set, not
  acquired under the present two-document claim.
- Start with focused RED, implement the owning behavior, verify GREEN, and run
  affected adversarial/integration checks. Full canonical tests follow material
  implementation; prose preparation does not run full pytest.
- Do not commit/push a runtime task without its separately approved publication
  boundary. Proposed commit labels below do not supply publication authority.

## Review focus

1. A new intent/context/journal alias during UNKNOWN must still be held (T2,T3).
2. Crash after broker acceptance or accounting post but before acknowledgement
   must not resubmit or double-post (T2,T3,T5).
3. Missing fees or rounded average prices must not become known zero/exact cash
   reconciliation (T1,T4,T5).
4. Direct legacy calls, hidden transport retries and forged capability models
   must refuse before I/O (T3,T4,T6).
5. Late fills, out-of-order evidence and stale resolution authority must not
   disappear behind pause, cancellation or a cached terminal status (T2,T5,T6).

## Gate 0: prerequisites before any implementation

- [ ] Read live #411/comments, current main, all proposed-path claims and open
  PR file lists; preserve #376/#378/#409 and other writer reservations.
- [ ] Read back the exact independently reviewed spec/plan hashes and an
  authorized ruling accepting or amending G3. Do not treat AI critique as human
  consumer acceptance or an authorized operational decision.
- [ ] Record the accepted registry/custodian, evidence and ordering profile,
  account hold/resume/expiry policy, executor quiescence/egress-fencing mechanism
  and migration scope. These must be actual
  approved inputs, not numbers or identities chosen by the implementer.
- [ ] Accept the single-store settlement contract and exact producer adapter
  path in T5. If absent, T5 and financial completion remain blocked; a fake
  adapter cannot substitute for this explicit requirement.
- [ ] Approve the complete runtime/test path inventory below and any named
  settlement-store amendment. Create/reuse a bounded implementation issue,
  isolated branch from refreshed main, and exact writer claim/readback.
- [ ] Read .python-version and uv.lock unchanged; inspect existing environment
  rather than copying another writer's virtualenv or credentials. Any required
  setup must be within that future offline runtime authorization.

## Task 1: versioned observations and verified authority boundary

**Files:** Create `src/drift/domain/execution_observation.py`,
`src/drift/execution/authority.py`, `tests/unit/test_execution_observation.py`,
`tests/unit/test_execution_authority.py`.
Read only `src/drift/domain/execution.py`, `src/drift/domain/common.py` and
`src/drift/serialization/canonical.py`.

**Interfaces:** Produces the exact records/protocols in spec sections 4,5,10:
ExecutionContextV2, ExecutionAttemptV2, ExecutionEvidenceV2,
BrokerStateFactV2, ExecutionObservationV2, ExecutionQuiescenceProofV2,
ExecutionResolutionV2, ExecutionResumeAuthorizationV2,
ExecutionAccountStateV2, VerifiedExecutionEvidenceV2, DispatchAuthorizationV2,
DispatchPermitV2, RecordedOperationV2, AuthorizationDecisionV2,
VerifiedLocalRefusalV2, VerifiedQuiescenceV2, VerifiedExecutionResolutionV2,
VerifiedExecutionResumeV2, SettlementEffectV2, SettlementReceiptV2,
ExecutionEvidenceVerifierV2 and ExecutionAuthorityV2.
Capabilities are internal verifier-issued objects, not JSON authority.

- [ ] RED: test_unknown_cannot_carry_current_report_or_fabricated_amounts;
  test_confirmed_requires_bound_evidence; test_not_sent_requires_no_send_marker;
  test_v1_zero_fee_without_evidence_is_incomplete. Assert UNKNOWN.report is None,
  historical reference remains historical and incomplete amounts cannot settle.
- [ ] RED: test_confirmed_fact_with_unknown_fee_has_no_v1_report. Assert
  knowledge=CONFIRMED, broker_fact.status=FILLED, exact known quantity retained,
  broker_fact.cum_fee_amount=None, report=None and accounting_state=incomplete.
  An unfamiliar status instead has knowledge=UNKNOWN and no current broker fact.
- [ ] RED: test_public_model_or_hash_is_not_authority;
  test_context_alias_cannot_change_account_key;
  test_capability_wrong_account_intent_epoch_refused. Assert no permissive
  default verifier/authority exists and copied/forged records are rejected.
- [ ] Run `uv run pytest tests/unit/test_execution_observation.py
  tests/unit/test_execution_authority.py -q`; confirm the intended missing
  types/behaviors fail. A typo or unavailable interpreter is not the desired RED.
- [ ] Implement only the declared records, canonical hashing/validation,
  bounded reason codes, registry/authority protocols and one-shot capability
  validation. Match the exact profile and discriminants in the spec.
- [ ] GREEN: rerun those tests plus `uv run pytest
  tests/unit/test_execution_domain.py -q`; unchanged V1 golden payloads validate.
- [ ] Review this interface boundary before consumers use it. Candidate commit
  label: `feat(execution): add versioned uncertainty observation contracts`.

## Task 2: durable attempt, hold, migration and resumption journal

**Files:** Modify `src/drift/execution/journal.py`,
`tests/unit/test_execution_journal.py`; create
`tests/integration/test_execution_uncertainty_journal.py`.

**Consumes:** T1 records and verifier-issued capabilities.
**Produces:** PersistentOrderIntentJournal.record_request_v2(context, intent,
operation, parent_attempt_id), load_operation_v2(attempt_id),
issue_dispatch_permit_v2(attempt_id, authorization),
consume_dispatch_permit_v2(permit), record_not_sent_v2(attempt_id, refusal),
record_observation_v2(verified), account_state_v2(account_key),
record_resolution_v2(verified), record_resume_v2(verified).
Use exact signatures/return types from spec section10. Request recording does
not require successful dispatch authorization. Grant, issued permit, consumed
permit and verified refusal are distinct. Public observation/authority models
cannot be committed as verified evidence or mint a permit.

- [ ] RED: test_prepare_intent_and_account_reservation_are_atomic;
  test_send_started_is_committed_before_transport;
  test_new_attempt_uuid_cannot_duplicate_logical_submit;
  test_two_processes_cannot_reserve_same_submission. Assert one logical root,
  one winning permit and no I/O after failed commit.
- [ ] RED: test_restart_replays_every_pending_operation;
  test_crash_each_dispatch_boundary_preserves_hold;
  test_fresh_context_or_copied_journal_is_not_authority;
  test_storage_failure_never_releases_account. Use subprocesses and actual
  reopened temporary SQLite databases, not only a new in-memory Python object.
- [ ] RED: test_resolution_epoch_changes_invalidate_resume;
  test_missing_or_expired_resume_authority_refused;
  test_authorization_refusal_records_not_sent_without_dispatch_grant;
  test_abandon_revokes_unconsumed_permits_atomically;
  test_restart_loads_original_intent_token_and_order_binding;
  test_restart_without_broker_id_can_reconcile_original_token;
  test_public_observation_cannot_bypass_verifier;
  test_concurrent_cumulative_observations_allocate_nonoverlapping_effects;
  test_pending_unacknowledged_effect_is_already_allocated;
  test_full_legacy_history_classification_preserves_bytes;
  test_incomplete_migration_or_old_writer_refuses_open.
- [ ] Run `uv run pytest tests/unit/test_execution_journal.py
  tests/integration/test_execution_uncertainty_journal.py -q`; retain the
  specific invariant failures before implementing.
- [ ] Add the append-only V2 tables/triggers and BEGIN IMMEDIATE transitions
  from spec section6. Account pending/hold checks, logical uniqueness and
  reservation insertion are atomic. Do not alter old tables or trigger rules.
- [ ] Add replay-derived account state, registry/journal lineage checks,
  full-history migration classifications and verified watermark. Never rewrite
  legacy uncertainty as a confirmed outcome or infer recovery from a timeout.
- [ ] In record_observation_v2's one transaction, validate ordering, read the
  allocated quantity/exact-notional/fee frontier, derive the next effect, append
  its outbox/allocation and advance the frontier. Do not use acknowledged state
  or observation UUIDs as economic identity. For cumulative 5 and 10, assert
  allocations total 10, never 15; hold unsupported fee-only/corrective deltas.
- [ ] GREEN: repeat the focused command; verify two real processes and every
  crash boundary. Check old rows, schema/triggers and payload bytes unchanged.
- [ ] Candidate commit label: `feat(execution): persist uncertainty and restart barriers`.

## Task 3: guarded V2 router and protocol

**Files:** Modify `src/drift/execution/adapter.py`,
`src/drift/execution/router.py`, `src/drift/execution/__init__.py`,
`tests/unit/test_execution_router.py`, `tests/unit/test_execution_adapter.py`;
modify `tests/adversarial/test_m14_broker_neutral_adversarial.py` and
`tests/unit/test_execution_safety_risk.py`;
create `tests/adversarial/test_execution_uncertainty.py`.

**Consumes:** T1 authority/evidence protocols and T2 journal transitions.
**Produces:** BrokerAdapterProtocolV2 and ReconciledExecutionRouterV2 with
submit(intent), cancel(intent_id, authorization), reconcile(attempt_id),
resolve(resolution), resume(authorization), returning the types in spec10.
Bind context, authority, verifier, journal and adapter at construction.

- [ ] RED: test_adapter_consumes_one_permit_before_one_transport_invocation;
  test_unknown_blocks_same_and_fresh_intents;
  test_retry_after_reopen_never_calls_place_twice;
  test_public_permit_model_cannot_authorize_io.
- [ ] RED: test_v1_mutation_methods_refuse_for_every_adapter;
  test_unregistered_adapter_or_journal_refused;
  test_missing_authority_is_not_a_default_allow;
  test_stale_permit_or_resume_epoch_never_dispatches.
- [ ] RED: test_paused_consumed_sender_blocks_resolution_without_quiescence;
  test_fenced_old_generation_cannot_send_after_resume. Use controlled suspension
  after committed consumption and before fake transport entry, plus separate
  restart tests. Empty broker readback must not satisfy quiescence.
- [ ] Run `uv run pytest tests/unit/test_execution_router.py
  tests/unit/test_execution_adapter.py
  tests/adversarial/test_m14_broker_neutral_adversarial.py
  tests/unit/test_execution_safety_risk.py
  tests/adversarial/test_execution_uncertainty.py -q` and observe intended RED.
- [ ] Implement the V2 router/protocol, one-shot durable dispatch and UNKNOWN
  handling. No V1 return-type substitution, fallback transport or auto-resend.
  Keep history/read-only V1 builders and replay usable; reject old mutation.
- [ ] Migrate existing adversarial replay and hard-risk positive controls to
  V2 setup. Preserve exact risk-limit refusal reasons and zero transport calls;
  local refusal is NOT_SENT, not a fabricated broker rejection. Add separate
  V1 refusal assertions rather than dropping the old substantive coverage.
- [ ] Verify alias/new-context, concurrent/resumed worker and direct entry-point
  attacks. Assert fake transport invocation counts, not just returned labels.
- [ ] GREEN: repeat focused and T2 process tests. Candidate commit label:
  `feat(execution): guard all submission paths with durable uncertainty state`.

## Task 4: Robinhood observation mapping and offline evidence

**Files:** Modify `src/drift/adapters/robinhood/adapter.py`,
`src/drift/adapters/robinhood/transport.py`,
`src/drift/adapters/robinhood/__init__.py`,
`tests/unit/test_robinhood_adapter.py`, `tests/unit/test_robinhood_transport.py`,
`tests/unit/test_robinhood_sync.py`,
`tests/unit/test_execution_safety_robinhood.py`,
`tests/unit/test_execution_safety_audit.py`,
`tests/adversarial/test_m16_robinhood_adapter_adversarial.py`.

**Consumes:** V2 protocol/permit, exact original intent/token, registered
evidence verifier. **Produces:** ExecutionEvidenceV2 candidates. The registered
verifier, coordinator and journal produce committed observations. A transport
result is evidence to verify, not trusted authority merely because it is a dict.

- [ ] RED: test_timeout_after_acceptance_and_failed_lookup_is_unknown;
  test_empty_lookup_does_not_prove_nonreceipt;
  test_unknown_raw_status_never_becomes_rejected;
  test_confirmed_rejection_is_distinct_from_local_not_sent.
- [ ] RED: test_cancel_timeout_after_partial_fill_retains_last_confirmed;
  test_confirmed_fill_with_missing_fee_remains_accounting_incomplete;
  test_rounded_average_is_not_exact_notional;
  test_transport_side_effect_retry_disabled;
  test_direct_legacy_adapter_mutation_refuses_before_io.
- [ ] Run `uv run pytest tests/unit/test_robinhood_adapter.py
  tests/unit/test_robinhood_transport.py tests/unit/test_robinhood_sync.py
  tests/unit/test_execution_safety_robinhood.py
  tests/unit/test_execution_safety_audit.py
  tests/adversarial/test_m16_robinhood_adapter_adversarial.py -q`; distinguish
  real new RED from retained unrelated S1/S3/S5 defects.
- [ ] Implement V2 mapping, explicit unfamiliar-status refusal/UNKNOWN,
  same-token bounded reconciliation and missing-measurement classification.
  A known fill without a fee produces CONFIRMED BrokerStateFactV2 with report=None,
  not a fabricated zero-fee report or a claim that its recognized status is unknown.
  No real transport, credential reads or inferred provider API capabilities.
- [ ] Migrate sync test setup from direct V1 mutation to V2 verified fake
  transport operations; retain cash/position synchronization assertions.
- [ ] Replace only S3/S4 defect-preserving expectations that the accepted repair
  actually resolves with active safety regressions. Remove the corresponding
  strict xfail only when the positive safety assertion demonstrably passes.
  Do not delete unrelated xfails or weaken the expectation to accept UNKNOWN
  without proving the hold and no-duplicate transport behavior.
- [ ] GREEN: repeat focused, restart and adversarial tests with sockets disabled.
  Candidate commit label: `fix(robinhood): preserve unconfirmed execution outcomes`.

## Task 5: single-store settlement contract and consumer accounting

**Files:** Create `src/drift/execution/settlement.py`,
`tests/unit/test_execution_settlement.py`,
`tests/integration/test_execution_uncertainty_settlement.py`;
modify `src/drift/domain/execution_observation.py` and
`src/drift/execution/journal.py` for accepted effect/outbox records.
The selected authoritative account-store adapter path must be named in G3/G4
before this task. This is an explicit prerequisite, not a wildcard file grant.
Read only `src/drift/evaluator/portfolio.py` and
`src/drift/domain/evaluator_portfolio.py` unless a separate amendment is accepted.

**Consumes:** verified observations and the accepted single account's durable
posting interface. **Produces:** ExecutionSettlementSinkV2.post_once(effect:
SettlementEffectV2) -> SettlementReceiptV2; a durable deduped effect key and
account-store commit/book revision. An identical replay returns the same
receipt; conflicting payload reuse raises a refusal. No second ledger/engine.

- [ ] Verify the selected store implements atomic key-plus-financial-fact
  posting and recoverable M2 kernel projection. Today's canary grader and
  in-memory apply_fill do not prove this property. If the producer contract is
  not accepted, leave this task blocked and do not mark A1 implemented.
- [ ] RED: test_partial_cumulative_fill_posts_only_verified_delta;
  test_same_effect_replay_returns_same_receipt;
  test_conflicting_effect_key_refused;
  test_crash_after_post_before_outbox_ack_cannot_double_book.
- [ ] RED: test_unknown_fee_or_exact_notional_prevents_complete_settlement;
  test_lower_or_conflicting_cumulative_evidence_holds_account;
  test_pending_post_then_later_fill_uses_allocated_frontier;
  test_unchanged_quantity_fee_evidence_never_posts_another_fill;
  test_projection_rebuild_does_not_reapply_into_mutated_kernel.
- [ ] Run `uv run pytest tests/unit/test_execution_settlement.py
  tests/integration/test_execution_uncertainty_settlement.py -q` and require
  actual transactional store tests in addition to a fake-sink outbox unit test.
- [ ] Implement the accepted outbox/sink adapter, durable dedupe receipt and
  projection replay. Keep last-known status separate from current exposure,
  incomplete costs and known quantities. No writes to old report history.
- [ ] GREEN: verify exact account/share/cash/cost arithmetic and restart cases.
  Candidate commit label: `feat(execution): reconcile confirmed effects exactly once`.

## Task 6: explicit validation, canary and autonomy consumers

**Files:** Modify `src/drift/validation/engine.py`,
`src/drift/canary/orchestrator.py`, `src/drift/canary/settlement.py`,
`src/drift/autonomy/orchestrator.py`,
`tests/unit/test_paper_validation_engine.py`,
`tests/unit/test_canary_orchestrator.py`, `tests/unit/test_canary_settlement.py`,
`tests/unit/test_autonomy_orchestrator.py`,
`tests/adversarial/test_m15_paper_validation_adversarial.py`,
`tests/adversarial/test_m17_canary_adversarial.py`,
`tests/adversarial/test_m18_bounded_autonomy_adversarial.py`;
modify `tests/integration/test_paper_trading_demo.py`;
create `tests/integration/test_execution_uncertainty_consumers.py`.

**Consumes:** T3 V2 router and T5 verified/deduped settlement receipts.
**Produces:** explicit consumer handling of UNKNOWN, NOT_SENT, incomplete
measurements and confirmed outcomes. No truthy flag certifies broker/account
readiness or scientific eligibility. Keep all these tests offline.

- [ ] RED: test_unknown_never_grades_settled_or_ready;
  test_not_sent_is_not_counted_as_broker_rejection;
  test_late_fill_after_pause_is_retained_once;
  test_stale_resume_does_not_override_risk_or_user_pause.
- [ ] RED: test_consumer_cannot_reach_legacy_adapter_mutation;
  test_confirmed_missing_fee_has_no_complete_result;
  test_direct_settlement_grader_rejects_unknown_or_incomplete_evidence;
  test_finalize_summary_refuses_unresolved_execution_or_unverified_equity.
  Assert IncompleteExecutionSummaryError and no persisted clean V1 summary;
  a caller equity value or empty slippage list must not substitute for evidence.
- [ ] Run `uv run pytest tests/unit/test_paper_validation_engine.py tests/unit/test_canary_orchestrator.py tests/unit/test_canary_settlement.py tests/unit/test_autonomy_orchestrator.py tests/adversarial/test_m15_paper_validation_adversarial.py tests/adversarial/test_m17_canary_adversarial.py tests/adversarial/test_m18_bounded_autonomy_adversarial.py tests/integration/test_paper_trading_demo.py tests/integration/test_execution_uncertainty_consumers.py -q`;
  observe the intended consumer failures rather than unrelated environment errors.
- [ ] Migrate public return/handling paths explicitly. UNKNOWN increments no
  filled/settled/success metric; preserve auditable unavailable/completeness
  classification. Reuse the existing accounting producer and accepted receipts.
- [ ] Migrate the existing paper-demo integration to V2 setup and preserve its
  substantive risk/accounting assertions. Keep a separate universal legacy
  mutation refusal control; there is no V1 mock-mutation compatibility exception.
- [ ] GREEN: positive controls for confirmed acceptance, fill, rejection and
  cancellation plus the negative authorization controls. Candidate commit label:
  `feat(execution): consume uncertainty without clean-result laundering`.

## Task 7: verification, documentation and independent implementation review

**Files:** Modify `docs/architecture/execution-safety-audit.md` only within the
future approved implementation write-set. Current #411 spec/plan remain the
design references. Additional canonical docs require named amendments.

- [ ] Map A01-A14 and R01-R12 to actual test names/results. Require multi-process
  crash/concurrency and real-store settlement evidence; unit labels alone are
  insufficient. Classify failures as regression/base/infrastructure/dependency
  or environment mismatch with exact evidence.
- [ ] Run focused tests from T1-T6, then unchanged canonical commands:
  `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy src tests`, `uv build`, `git diff --check` and
  `git diff --check <verified-base-sha> HEAD` against the then verified base.
- [ ] Verify V1 payload bytes and expected hashes against the unchanged
  baseline. Classify new implementation fingerprints separately; never repair
  pins, hashes or fixtures merely to pass. Preserve legitimate xfail evidence.
- [ ] Update only proven S3/S4 audit claims, including remaining limitations,
  accepted decision revision, authority and tested environment. Retain S1/S5
  and separate source/scientific/operational blockers.
- [ ] Obtain fresh independent implementation/adversarial review of the exact
  diff/head after material corrections. AI review does not replace required
  human consumer or authorized architecture acceptance.
- [ ] Refresh main/head/claims. Under separate publication authority, stage
  individually enumerated approved files, commit normally, push normally and
  use one draft PR. Follow exact-head CI to terminal result; cancelled or old
  success is not a pass. Keep issue/PR open and draft absent separate authority.

## Requirement coverage and present execution state

- R01/R11, A01/A02/A03/A08/A13: T1,T4,T5,T6.
- R02/R10, A11: T1,T2,T7.
- R03/R04, A05/A06: T2,T3,T4.
- R05/R08/R09, A04/A14: T1,T2,T3,T4,T6.
- R06/R07, A07/A09/A10: T2,T5,T6.
- R12/A12: Gate0 and all tasks, especially positive fake-authority controls.

No implementation step above has run. No proposed module/type/database table
exists as a result of this plan. Actual current work is two documentation files,
document checks and independent architecture critique. Required runtime,
consumer, publication and operational approvals remain separate gates.
