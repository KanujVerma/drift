# K1-K5 legacy delivery reconciliation: November 2, 2026

## Scope and authority

[Cleanup issue #584](https://github.com/KanujVerma/drift/issues/584) records
this pass. Kanuj authorized repository cleanup. That authorization does not
create producer acceptance, scientific acceptance, source qualification, or
trading permission. This file is the requirement and test matrix for six
legacy delivery pull requests. It does not change production source, tests,
fixtures, pins, or CI.

The preceding cleanup record remains
[repository-cleanup-2026-11-02.md](repository-cleanup-2026-11-02.md). Its
historical statements are not rewritten here.

## Baseline

Prompt snapshot, not used as a mutation base:

- `main` `16a47d7cf8daadd917e786630220405f08eb2a6c`
- 37 open pull requests, 73 open issues
- post-merge documentation CI run
  [41498827736](https://github.com/KanujVerma/drift/actions/runs/41498827736)
  was still `in_progress` when this file was written. Its `updatedAt` remained
  `2026-11-02T18:15:32Z`. Conclusion: pending. It is not recorded as a pass.

Refreshed state before the six-PR disposition:

- `origin/main` `79c79cdcc31322154f12d654edef3261fbc9e69f`
- parent `16a47d7cf8daadd917e786630220405f08eb2a6c`
- that main commit is the merge of
  [PR #581](https://github.com/KanujVerma/drift/pull/581) at head
  `23c41adf8f6eadd72a970854e30f9f964e6d1c98`
- open pull requests: 36
- open issues after reopening #575 and opening #584: 73

| PR | Issue | Head verified not an ancestor of `79c79cd` | Unique commits ahead of main |
| --- | --- | --- | --- |
| #447 | #401 | `9ebb0f436c38adf9b78a52bab071ef5bcad6100f` | 1 |
| #449 | #402 | `b649196a148f3eea1ddc7d8ef7d121dc2037d8e2` | 2 |
| #450 | #403 | `9e1fe54ecf8525b7ae8adeb1a2aa23aa0d239b4b` | 3 |
| #451 | #404 | `08574f99933997a067aa6a2324f1ad74ed6255c8` | 4 |
| #452 | #405 | `a4a3949ffbbf6753fcd250ccd48afa71478a6148` | 5 |
| #454 | #453 | `04ec06dfa9c84a6c48be42783b8bf4527fbbcc6e` | 3 |

No original test function name from those heads is absent on `origin/main`.
`tests/fixtures/adaptive_research/research_v1.json` and
`tests/fixtures/adaptive_research/model_replay_v1.json` match the original
heads byte for byte. Body differences that were inspected are additional
assertions or a move of the M1e scan into `_assert_m1e_source_file_allowed`.
Replacement code arrived through merged
[PR #457](https://github.com/KanujVerma/drift/pull/457)
([issue #456](https://github.com/KanujVerma/drift/issues/456), closed
completed), merged [PR #465](https://github.com/KanujVerma/drift/pull/465)
(`832bebbe2d28632dcfbce1002f44386ef87cdf2e`, ancestor of main), and the
already-incorporated heads of #467, #470, #474, and #476. Those four were
closed in the #582 pass without a second merge. Their heads were ancestors of
main. This pass does not merge the six older branches.

## Focused tests

Command, from the isolated worktree at `79c79cd`, pinned interpreter, unchanged
`uv.lock`:

```text
uv run pytest tests/unit/test_intelligence_contracts.py \
  tests/unit/test_intelligence_validation.py \
  tests/unit/test_intelligence_receipts.py \
  tests/unit/test_intelligence_model_replay.py \
  tests/unit/test_intelligence_conventional_selector.py \
  tests/unit/test_intelligence_proposal_producer.py \
  tests/unit/test_intelligence_context_builder.py \
  tests/unit/test_intelligence_learning.py \
  tests/adversarial/test_intelligence_causality.py \
  tests/unit/test_intelligence_review_scheduler.py \
  tests/unit/test_intelligence_platform_bridge.py \
  tests/integration/test_m1e_compatibility.py \
  -q --tb=line -p no:cacheprovider
```

Result: CPython 3.14.6, 344 passed, 6 warnings, 4.50s, exit 0. A green run is
not the equivalence proof. The matrix below names the assertions.

Read-only probe, not a committed test: two conventional candidates scored
`Decimal("1")` and `Decimal("1") - Decimal("0.0000000005")` select the better
`(family, parameters_hash, candidate_id)` key. A gap of
`Decimal("0.000000002")` selects the higher score. That matches
`conventional_selector.py` lines 301-308. No committed test asserts the
inside-band case. Equal-score tests would still pass if the band were removed.

## Requirement matrix

Status values used below are `EXACTLY_PRESERVED`,
`SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR`,
`INTENTIONALLY_REPLACED_BY_ACCEPTED_POLICY`, and `MISSING_TEST_EVIDENCE`.
No row in this matrix is `MISSING_IMPLEMENTATION`, `CONFLICTING_REQUIREMENTS`,
or `UNVERIFIED`.

### K1, PR #447

Current modules: `src/drift/intelligence/contracts.py`,
`src/drift/intelligence/validation.py`. Hardening commit is the #465 merge.

| Requirement | Status | Current evidence |
| --- | --- | --- |
| Immutable context, candidate, and artifact contracts | EXACTLY_PRESERVED | `test_f01_research_context_deserialization`, `test_f02_research_candidate_deserialization`, `test_immutability_enforced` |
| Canonical hashes and original validation | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_positive_abstention_validation_matches_f03` now hashes the raw abstain bytes instead of a dummy digest |
| Strategy and parameter identity | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_a_self_rehashed_candidate_must_preserve_local_eligibility_invariants`, `test_a_mismapped_registry_family_cannot_be_selected` |
| Portfolio target and cash-weight constraints | EXACTLY_PRESERVED | `test_target_weight_validation` |
| Abstain, hold, and propose semantics | EXACTLY_PRESERVED | `test_f03_abstention_deserialization`, `test_positive_abstention_validation_matches_f03` |
| Extra-field, malformed-type, and rehashed-object refusal | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_extra_keys_forbidden`, `test_forged_typed_choice_is_not_trusted_without_revalidation`, `test_rehashed_context_cannot_promote_synthetic_source` |
| Wrong account, policy, and scope refusal | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_negative_cases_n01_to_n12` passes `context` for N05 and N07 |
| Original positive and adversarial fixtures | EXACTLY_PRESERVED | `research_v1.json` matches the #447 head |
| Preserved persisted profiles and hashes | EXACTLY_PRESERVED | same fixture bytes; tests still load F01-F08 |
| Caller-recomputed hash cannot bypass validation | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_forged_frozen_context_and_invocation_cannot_authorize_choice` |

Disposition: `PROVEN_SUPERSEDED`.

### K2, PR #449

Current modules: `src/drift/intelligence/receipts.py`,
`src/drift/intelligence/model_replay.py`. Incorporated correction: #467 head
`ffc688e4672ff2a62013c292d2fb2141243c52c4`.

| Requirement | Status | Current evidence |
| --- | --- | --- |
| Started and terminal attempt lineage | EXACTLY_PRESERVED | `test_t09_attempt_lifecycle_chaining` |
| Append-only events and receipts | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_recovery_rejects_out_of_order_and_tampered_events_atomically`, `test_canonical_receipt_bytes_roundtrip_and_truncation` |
| Duplicate idempotency and conflicting duplicate refusal | EXACTLY_PRESERVED | `test_t10_store_idempotency_and_integrity` |
| Verified zero, unknown, estimated, and actual cost | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t10_cost_identity_and_adjustments`, `test_scripted_nonzero_cost_is_an_estimate_not_an_actual_bill` |
| Correction and supersession accounting | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_cost_correction_requires_actual_predecessor_and_same_scope`, `test_k2_disallows_competing_corrections_without_dropping_history` |
| Contradictory cost-evidence refusal | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_k2_rejects_contradictory_cost_inputs` |
| Timestamp and chronology validation | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_k2_rejects_noncausal_cost_timestamps_at_creation_and_replay` |
| Crash recovery keeps unresolved attempts | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t11_crash_recovery_preserves_unresolved` is longer on main than on the #449 head |
| Deterministic offline model replay | EXACTLY_PRESERVED | `test_t06_positive_model_replay_and_zero_network`, `test_repeated_replay_produces_identical_evidence_identity` |
| Missing and malformed source or provider evidence | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t06_negative_replay_cases`, `test_malformed_or_ambiguous_model_json_is_not_a_valid_decision` |
| No invented provider charge, issuer fact, or completed outcome | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_replay_cannot_invent_a_provider_stop_reason`, `test_mismatched_response_presence_cannot_be_reported_as_timeout` |

Disposition: `PROVEN_SUPERSEDED`.

### K3, PR #450

Current modules: `src/drift/intelligence/conventional_selector.py`,
`src/drift/intelligence/proposal_producer.py`. Incorporated correction: #470
head `936c97236a85b1b768b2c9ad8e5cef7e068506f8`, which introduced
`Decimal("0.000000001")`. Stage 1 exact incumbent ties live separately in
`src/drift/intelligence/stage1_conventional_policy.py` and were not edited.

| Requirement | Status | Current evidence |
| --- | --- | --- |
| Entire candidate pool validated before scoring | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_r_rejects_entire_pool_if_any_member_invalid` |
| One invalid candidate cannot shrink the frozen pool | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | same test, plus `test_r_freezes_pool_before_objective_side_effects` |
| Objective failures and mutation resistance | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_r_invalid_objective_never_selects_a_candidate`, `test_r_opaque_pool_refuses_before_deepcopy_side_effects` |
| Candidate, method, policy, context, and invocation identity | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_r_attempts_bind_policy_request_and_context_profile`, `test_scripted_identity_binds_request_and_candidate_ttl` |
| Distinct attempts and replay provenance | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_noncanonical_pool_without_explicit_attempt_id_cannot_claim_replay_identity` |
| Exact-score deterministic tie | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_conventional_selection_deterministic_tie_breaking` retained; `test_r_tie_breaks_on_actual_parameter_digest` asserts the winner across pool order |
| DP-R6 scores within `1e-9` tie | MISSING_TEST_EVIDENCE | Implementation and the read-only probe agree. No committed test uses a nonzero gap inside `Decimal("0.000000001")` |
| Stage 1 exact incumbent tie policy | INTENTIONALLY_REPLACED_BY_ACCEPTED_POLICY | Separate function `select` path in `stage1_conventional_policy.py`. Not used as a substitute for DP-R6 |
| Terminal and cost-receipt ordering | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_conventional_selection_optimal_candidate` asserts `budget_ref` then `completed` |
| Malformed response, timeout, and unknown cost | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t07_malformed_json_failure`, `test_t07_timeout_failure`, `test_invalid_synthetic_billing_retains_a_terminal_and_unknown_cost` |
| Separate AI and R attempt stores | EXACTLY_PRESERVED | `test_ai_and_r_attempt_stores_do_not_leak_across_arms` |

Disposition: `PARTIALLY_SUPERSEDED`. The pull request stays open. The remaining
proof is one regression test on the existing DP-R6 band. Tracking issue: #469.
Krish has not confirmed that handoff, so #450 is not closed in this pass.

### K4, PR #451

Current modules: `src/drift/intelligence/context_builder.py`,
`src/drift/intelligence/learning.py`, and
`tests/adversarial/test_intelligence_causality.py`. Incorporated correction:
#474 head `ab7ed779cc23a4ab50b86be3706395c181bda211`.

| Requirement | Status | Current evidence |
| --- | --- | --- |
| Time-of-decision cutoff | EXACTLY_PRESERVED | `test_t01_t02_post_cutoff_input_rejection`, `test_adversarial_t01_t02_subsecond_lookahead_refusal` |
| Sealed holdout exclusion | EXACTLY_PRESERVED | `test_t05_holdout_access_violation`, `test_adversarial_t05_sealed_holdout_contamination_prevented` |
| Cross-arm isolation | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t04_cross_arm_input_filtering`, `test_adversarial_t04_cross_arm_memory_leakage_prevented` |
| Deterministic deduplication and ordering | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_equal_bytes_different_sources_preserved_and_permutation_stable`, `test_adversarial_order_perturbation_invariance` |
| Versioned immutable learning snapshots | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_learning_hash_binds_method_clock_and_predecessor`, `test_self_rehashed_snapshot_must_have_coherent_version_ancestry` |
| Matured feedback only | EXACTLY_PRESERVED | `test_t01_unmatured_feedback_excluded` |
| Genuine negative-PnL observations retained | EXACTLY_PRESERVED | `test_t12_complete_losing_trial_admitted` |
| Malformed or conflicting revisions rejected | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_learning_rejects_conflicting_trial_revision`, `test_same_source_revision_conflicting_bytes_rejected` |
| Duplicate trial, cyclic predecessor, and caller mutation refused | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_self_rehashed_duplicate_trial_history_is_refused`, `test_learning_uses_independent_copy_of_caller_feedback_metrics` |
| Causal memory readback | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_adversarial_future_revision_cannot_rewrite_matured_memory` |
| Rehashed record cannot admit future or peer-arm feedback | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_self_rehashed_invalid_prior_feedback_never_enters_learning`, `test_adversarial_sealed_peer_arm_input_refused_before_filtering` |

Disposition: `PROVEN_SUPERSEDED`.

### K5, PR #452

Current modules: `src/drift/intelligence/review_scheduler.py`,
`src/drift/intelligence/platform_bridge.py`. Incorporated correction: #476
head `154789628a7acb146353e59b01eba319f047e7bb`. The bridge module is one of
the eleven scanned intelligence paths, so the no-network boundary is the M1e
guard rather than a live broker test.

| Requirement | Status | Current evidence |
| --- | --- | --- |
| Weekly, monthly, and event-driven schedules | EXACTLY_PRESERVED | `test_routine_review_trigger_due`, `test_planned_adaptation_trigger_due`, `test_t03_event_driven_trigger_and_cooldown` |
| Materiality, cooldown, and event deduplication | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_materiality_changes_trigger_identity`, `test_exact_duplicate_feed_event_is_idempotent`, `test_event_cooldown_does_not_block_routine_or_adaptation` |
| Broken, unknown, and confirmed-empty feeds stay distinct | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t03_feed_condition_evaluations`, `test_contradictory_feed_status_cannot_be_hidden_by_unavailable_result` |
| Calendar revision, timing, and arrival validation | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t02_calendar_revision_conflict_refusal`, `test_future_calendar_and_naive_time_are_not_available` |
| Deterministic defensive-only constraints | EXACTLY_PRESERVED | `test_d05_defensive_only_policy_validation` |
| Candidate, portfolio, mandate, and state reference matching | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_full_portfolio_and_mandate_refs_must_match_even_with_same_hash` |
| Expiration, stale portfolio, and unknown execution refusal | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_t08_stale_candidate_expired_refusal`, `test_t08_stale_portfolio_state_refusal`, `test_unknown_account_verification_is_not_safe` |
| Pending-order and pause behavior | EXACTLY_PRESERVED | `test_t08_pending_orders_conflict_refusal`, `test_t08_account_paused_refusal` |
| No dispatch from rejected or invalid candidates | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_stage1_empty_propose_refuses_before_platform`, `test_self_rehashed_invalid_weights_never_make_a_platform_request` |
| Next-open fallback only under explicit policy | EXACTLY_PRESERVED | `test_t14_admitted_candidate_next_open_fallback`, `test_t14_unsupported_intraday_without_fallback` |
| No retrospective decision or quote leakage | EXACTLY_PRESERVED | `test_t14_lookahead_violation_refusal`, `test_future_event_revision_cannot_invalidate_past_review` |
| No network, broker, or capital | EXACTLY_PRESERVED | `platform_bridge.py` is inside `INTELLIGENCE_SOURCE_PATHS` and passed `test_intelligence_capability_guard_is_nonvacuous` |

Disposition: `PROVEN_SUPERSEDED`.

### Offline intelligence gate, PR #454

Current scanner: `tests/integration/test_m1e_compatibility.py`.
`INTELLIGENCE_SOURCE_PATHS` has these eleven paths, and
`test_intelligence_source_inventory_is_exact_and_nonempty` asserts that count:

- `src/drift/intelligence/__init__.py`
- `src/drift/intelligence/contracts.py`
- `src/drift/intelligence/validation.py`
- `src/drift/intelligence/receipts.py`
- `src/drift/intelligence/model_replay.py`
- `src/drift/intelligence/proposal_producer.py`
- `src/drift/intelligence/conventional_selector.py`
- `src/drift/intelligence/context_builder.py`
- `src/drift/intelligence/learning.py`
- `src/drift/intelligence/review_scheduler.py`
- `src/drift/intelligence/platform_bridge.py`

`test_m1e_additions_are_allowlisted_inert_and_leave_m1d_pins_unchanged` is
shorter than the #454 copy because the per-file branch now calls
`_assert_m1e_source_file_allowed`, which reads source bytes and dispatches
the intelligence allowlist. Byte-aware parsing arrived in merged #561
(`66987cea709053260814382eea72a75c565277d2`). M1d pins and `uv.lock` checks in
that test were not relaxed.

| Requirement | Status | Current evidence |
| --- | --- | --- |
| Exact K1-K5 paths are scanned, not only listed | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `_assert_m1e_source_file_allowed` plus the inventory test |
| Unknown additional source file refused | EXACTLY_PRESERVED | inventory test rejects `unknown_future.py`; unregistered files fail the helper |
| Network import and invocation refused | EXACTLY_PRESERVED | `test_intelligence_capability_guard_is_nonvacuous` includes `import socket` |
| Environment reads refused | EXACTLY_PRESERVED | same test includes `os.environ.get` and `/proc/self/environ` |
| Subprocess and process invocation refused | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | same test, plus `test_production_ast_guard_rejects_alias_aware_process_and_dynamic_execution` |
| Dynamic execution refused | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | alias-aware process and dynamic-execution test |
| Shadowed capability definitions refused | EXACTLY_PRESERVED | exact eleven-path set; a new intelligence module is not auto-exempt |
| Mutated bytes and invalid encoding refused | SUPERSEDED_BY_STRONGER_VERIFIED_BEHAVIOR | `test_actual_file_scans_fail_closed_on_invalid_source_encodings`, `test_actual_file_scans_refuse_declared_codec_hidden_operations`, `test_pinned_preflight_actual_file_dispatch_and_mutation_refusal` |

Disposition: `PROVEN_SUPERSEDED`.

## Acceptance distinctions

Merged #457 and #465, and the incorporated #467, #470, #474, and #476 heads,
are engineering evidence. They are not Krish's, Matthew's, or an independent
reviewer's acceptance, and they are not source, provider, or trading approval.

Remaining review of the research contract stays on open
[#373](https://github.com/KanujVerma/drift/issues/373) and
[#375](https://github.com/KanujVerma/drift/issues/375). Research-to-trial
authority stays on open
[#507](https://github.com/KanujVerma/drift/issues/507). Scientific eligibility
stays on open [#485](https://github.com/KanujVerma/drift/issues/485) and
[#575](https://github.com/KanujVerma/drift/issues/575). #575 was reopened
because merged #581 had said `Resolves #575`. Reopen comment:
https://github.com/KanujVerma/drift/issues/575#issuecomment-6587231394.
Readback: `state` OPEN, `stateReason` REOPENED.

#580 stays closed. Its listed engineering files are on `79c79cd`, and
exact-head pull-request CI including pytest succeeded:
https://github.com/KanujVerma/drift/actions/runs/41478405542.
That closure is not study execution or scientific acceptance. Post-merge push
CI on `79c79cd` was pending:
https://github.com/KanujVerma/drift/actions/runs/41515319055.

The DP-R6 near-tie regression remains on open #469. #403 and #450 stay open
with it. No other new defect issue was opened.

## Pull-request disposition

| PR | Disposition | Next action |
| --- | --- | --- |
| #447 | PROVEN_SUPERSEDED | Close without merge. Retain `krish/401-k1-contracts`. |
| #449 | PROVEN_SUPERSEDED | Close without merge. Retain `krish/402-k2-receipts-replay`. |
| #450 | PARTIALLY_SUPERSEDED | Keep open until #469 has the near-tie test or Krish confirms the handoff. Retain `krish/403-k3-producers-seams`. |
| #451 | PROVEN_SUPERSEDED | Close without merge. Retain `krish/404-k4-causal-context-learning`. |
| #452 | PROVEN_SUPERSEDED | Close without merge. Retain `krish/k5-scheduler-platform-bridge`. |
| #454 | PROVEN_SUPERSEDED | Close without merge. Retain `krish/453-intelligence-m1e-capability-gate`. |

Closure comment URLs are appended in the execution addendum after the first
commit of this file, because the comment has to cite this committed path.

## Issue disposition for the K-series set

| Issue | Disposition | Reason |
| --- | --- | --- |
| #401 | COMPLETED_TRACKER | K1 engineering is on main via #457 and #465. Review remains on #373 and #375. |
| #402 | COMPLETED_TRACKER | K2 engineering is on main via #457 and incorporated #467. |
| #403 | ACTIVE_CRITICAL_PATH | Stays open only as the parent of the #469 test gap. Implementation otherwise matches the matrix. |
| #404 | COMPLETED_TRACKER | K4 engineering is on main via #457 and incorporated #474. |
| #405 | COMPLETED_TRACKER | K5 engineering is on main via #457 and incorporated #476. |
| #453 | COMPLETED_TRACKER | The eleven-path byte scanner and negative controls pass on main, including #561. |
| #464 | COMPLETED_TRACKER | #465 is merged and is an ancestor of main. Forged-candidate tests passed. |
| #466 | COMPLETED_TRACKER | Contradictory-cost and lineage tests passed. The #467 head is already in main history. |
| #469 | ACTIVE_CRITICAL_PATH | Remaining work is the committed DP-R6 inside-band regression. Owner: Krish. |
| #473 | COMPLETED_TRACKER | Causal and learning hardening tests passed. The #474 head is already in main history. |
| #475 | COMPLETED_TRACKER | Scheduler and bridge hardening tests passed. The #476 head is already in main history. |
| #456 | COMPLETED_TRACKER | Already closed completed by merged #457. Not reopened. |
| #373 | ACTIVE_CRITICAL_PATH | Parent producer feature. Not closed. |
| #375 | ACTIVE_CRITICAL_PATH | Parent research contract. Not closed. |
| #507 | ACTIVE_CRITICAL_PATH | Research-to-trial authority. Not closed. |

## G3 metadata

[PR #581](https://github.com/KanujVerma/drift/pull/581) was already merged, so
the description edit cannot undo the keyword closure. The description now
states nine calibration pairs, points at `verify_frozen_study`,
`ProductionStudyEvidenceVerifier`, and `advance_prospective_session`, marks
the Sol review at `c2a100e692b698620305c3e4a760ac0ee41d8cd0` as historical, and
records post-merge CI run 41515319055 as pending. No G3 source, test, fixture,
or branch content was edited. The local directory named
`kanuj-575-g3-implementation` was checked out on `main` and was not used.

## Post-cleanup CI from #583

Run [41498827736](https://github.com/KanujVerma/drift/actions/runs/41498827736)
on `16a47d7cf8daadd917e786630220405f08eb2a6c` was `in_progress` with an empty
conclusion at inventory time. No receipt was added to #582. Pre-merge
documentation CI is not substituted for this full-suite run. Current main is
`79c79cd`, so this run is not CI of current main even if it later succeeds.

## Remaining open-record inventory

Refreshed inventory: 36 open pull requests and 73 open issues, including #584.
This pass proved supersession only for the five K-series pull requests named
above. Every other open pull request below is retained. `updatedAt` is the
GitHub timestamp, not a claim that a human wrote on that instant.

| PR | Owner | Disposition | Outstanding work |
| --- | --- | --- | --- |
| #407 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #376 contract. |
| #408 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #378 source qualification. |
| #412 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #379 intraday contract. |
| #413 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #411 UNKNOWN execution. |
| #414 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #380 mandate contract. |
| #415 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #394 source envelope. |
| #416 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #395 recovery. |
| #417 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #396 containment. |
| #447 | Krish-Verma | PROVEN_SUPERSEDED | Close in this pass. |
| #449 | Krish-Verma | PROVEN_SUPERSEDED | Close in this pass. |
| #450 | Krish-Verma | PARTIALLY_SUPERSEDED | #469 near-tie test. |
| #451 | Krish-Verma | PROVEN_SUPERSEDED | Close in this pass. |
| #452 | Krish-Verma | PROVEN_SUPERSEDED | Close in this pass. |
| #454 | Krish-Verma | PROVEN_SUPERSEDED | Close in this pass. |
| #461 | KanujVerma | UNIQUE_UNMERGED_DELIVERY | Draft #460 E1 architecture. |
| #486 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | Draft #383 acceptance spec. |
| #487 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | Draft #381 offline triage. |
| #491 | matthew-philip | UNIQUE_UNMERGED_DELIVERY | Draft #423 admission guard. |
| #502 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | Draft #496 triage M1e inventory. |
| #513 | KanujVerma | UNIQUE_UNMERGED_DELIVERY | Draft #512 invocation grant. |
| #515 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | Draft #492 feed-closure fix. |
| #516 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | Draft #52 measured M1e runtime. |
| #517 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | Draft #135 M1d equality fix. |
| #522 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #520 recovery preflight candidate. |
| #523 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #521 containment preflight candidate. |
| #526 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #524 source-evidence preflight. |
| #527 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #525 execution-trace preflight. |
| #530 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #528 SRC replay preflight. |
| #531 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #529 mandate preflight. |
| #534 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #532 RESULT economics preflight. |
| #535 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #533 UNKNOWN replay preflight. |
| #538 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #536 QQQ replay preflight. |
| #539 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #537 forward-readiness preflight. |
| #541 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #540 retained K1 and E1 association. |
| #544 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #542 balanced-target enumerator. |
| #545 | Krish-Verma | UNIQUE_UNMERGED_DELIVERY | #543 V1 execution-evidence audit. |

Open issues not in the K-series table:

| Issue | Owner | Disposition | Outstanding work |
| --- | --- | --- | --- |
| #16 | Krish-Verma | BLOCKED_GENUINE_DEPENDENCY | M9 multi-agent research. |
| #52 | Krish | UNIQUE_UNMERGED_DELIVERY | Stale CPython pin. PR #516. |
| #100 | Krish | BLOCKED_GENUINE_DEPENDENCY | Evaluator evidence has no qualified replay context. |
| #101 | Krish | BLOCKED_GENUINE_DEPENDENCY | Caller-chosen bundle sets. |
| #115 | Krish | BLOCKED_GENUINE_DEPENDENCY | Promotion-lane prerequisites. |
| #135 | Krish | UNIQUE_UNMERGED_DELIVERY | M1d caller equality. PR #517. |
| #151 | Krish | BLOCKED_GENUINE_DEPENDENCY | Session-stamp and corporate-action binding. |
| #155 | unassigned | ACTIVE_NONCRITICAL | Completion ledger. Not proved complete. |
| #360 | Krish-Verma | BLOCKED_GENUINE_DEPENDENCY | Statistical evidence and promotion authorization. |
| #365 | unassigned | ACTIVE_NONCRITICAL | Venue calendar alignment. Protected calendar work. |
| #369 | Krish-Verma | BLOCKED_GENUINE_DEPENDENCY | Four-person queue activation. |
| #372 | KanujVerma | BLOCKED_GENUINE_DEPENDENCY | Offline news-event triage feature. |
| #374 | matthew-philip | BLOCKED_GENUINE_DEPENDENCY | Platform implementation parent. |
| #376 | matthew-philip | ACTIVE_CRITICAL_PATH | Source, triage, and result contract. PR #407. |
| #378 | matthew-philip | ACTIVE_CRITICAL_PATH | Data qualification. PR #408. |
| #379 | matthew-philip | ACTIVE_CRITICAL_PATH | Intraday execution contract. PR #412. |
| #380 | matthew-philip | ACTIVE_CRITICAL_PATH | Risk and approval contract. PR #414. |
| #381 | KanujVerma | BLOCKED_GENUINE_DEPENDENCY | Minimal screening feature. PR #487. |
| #383 | KanujVerma | BLOCKED_GENUINE_DEPENDENCY | First auditable vertical slice. PR #486. |
| #384 | matthew-philip | BLOCKED_GENUINE_DEPENDENCY | Paper and shadow authorization. |
| #390 | unassigned | BLOCKED_GENUINE_DEPENDENCY | Harsha migration receipts are not established. Preserved. |
| #391 | KanujVerma | BLOCKED_GENUINE_DEPENDENCY | Experiment system and scientific validation. |
| #394 | matthew-philip | ACTIVE_CRITICAL_PATH | Minimal source envelope. PR #415. |
| #395 | matthew-philip | ACTIVE_NONCRITICAL | Recovery boundaries. PR #416. |
| #396 | matthew-philip | ACTIVE_NONCRITICAL | Containment boundaries. PR #417. |
| #409 | matthew | ACTIVE_NONCRITICAL | QQQ offline replay. Protected historical benchmark work. |
| #411 | unassigned | ACTIVE_CRITICAL_PATH | UNKNOWN execution and resumption. PR #413. |
| #422 | Krish-Verma | ACTIVE_NONCRITICAL | K0 review. Not part of this six-PR matrix, so not closed. |
| #423 | matthew-philip | ACTIVE_NONCRITICAL | M0 admission guard. PR #491. |
| #428 | Krish-Verma | BLOCKED_GENUINE_DEPENDENCY | Markov study decision request. |
| #429 | matthew-philip | BLOCKED_GENUINE_DEPENDENCY | Markov interface request. |
| #430 | KanujVerma | BLOCKED_GENUINE_DEPENDENCY | Markov preregistration review. |
| #433 | Krish-Verma | BLOCKED_GENUINE_DEPENDENCY | Synthetic ensemble proposal. |
| #460 | KanujVerma | ACTIVE_NONCRITICAL | E1 architecture. PR #461. |
| #485 | KanujVerma | ACTIVE_CRITICAL_PATH | E6B typed producer evidence. Preserved. |
| #490 | Krish-Verma | ACTIVE_NONCRITICAL | Duplicate universe identities in K0 manifests. |
| #492 | KanujVerma | ACTIVE_NONCRITICAL | Feed completeness. PR #515. |
| #493 | matthew-philip | ACTIVE_NONCRITICAL | Keep admission orchestration outside the evaluator core. |
| #496 | matthew | ACTIVE_NONCRITICAL | News-triage M1e inventory. PR #502. Scanner not relaxed. |
| #501 | Krish-Verma | ACTIVE_NONCRITICAL | Frozen R, R-ML, and R-Hybrid formulas. |
| #508 | matthew-philip | ACTIVE_CRITICAL_PATH | RESULT-to-E1 authentication. |
| #512 | KanujVerma | ACTIVE_CRITICAL_PATH | Original E1 invocation grant. PR #513. |
| #520 | matthew | ACTIVE_NONCRITICAL | Recovery preflight assist. PR #522. |
| #521 | matthew | ACTIVE_NONCRITICAL | Containment preflight assist. PR #523. |
| #524 | matthew | ACTIVE_NONCRITICAL | Source qualification preflight. PR #526. |
| #525 | matthew | ACTIVE_NONCRITICAL | Execution trace preflight. PR #527. |
| #528 | matthew | ACTIVE_NONCRITICAL | SRC replay preflight. PR #530. |
| #529 | matthew | ACTIVE_NONCRITICAL | Mandate preflight. PR #531. |
| #532 | matthew | ACTIVE_NONCRITICAL | RESULT economics preflight. PR #534. |
| #533 | unassigned | ACTIVE_NONCRITICAL | UNKNOWN replay preflight. PR #535. |
| #536 | matthew | ACTIVE_NONCRITICAL | QQQ replay preflight. PR #538. |
| #537 | matthew | ACTIVE_NONCRITICAL | Forward-readiness preflight. PR #539. |
| #540 | unassigned | ACTIVE_CRITICAL_PATH | Retained K1 validation for #507. PR #541. |
| #542 | matthew | ACTIVE_NONCRITICAL | Balanced-target enumerator. PR #544. |
| #543 | matthew | ACTIVE_NONCRITICAL | V1 execution-evidence audit. PR #545. |
| #567 | Krish-Verma | ACTIVE_NONCRITICAL | Isolated Qlib comparator evaluation. |
| #568 | matthew-philip | ACTIVE_NONCRITICAL | Normal-loop failure conformance. |
| #575 | KanujVerma | ACTIVE_CRITICAL_PATH | Reopened G3 coordination. Source qualification, evidence, bindings, calibration execution, and prospective execution remain open. |
| #584 | Kanuj | ACTIVE_NONCRITICAL | This documentation pass. Closes when the documentation pull request merges. |

Critical-path engineering blockers that remain after the five superseded
pull requests close:

- Krish: committed DP-R6 inside-band regression on #469. #450 stays open until
  that test lands or Krish confirms the handoff.
- Kanuj: #575 historical qualification, original evidence, model bindings,
  real calibration runs, and prospective execution. Software for those steps
  is merged. The runs are not.
- Krish and Matthew: #507 and #508 trial binding, #485 scientific eligibility,
  and #390 migration receipts.
- Matthew: open contract drafts #376, #378, #379, #380, #394, and #411.

No remote branch is deleted in this pass.

## Counts

Before this pass, at the refreshed inventory: 36 open pull requests and 73
open issues. After the five superseded pull requests and the completed K-series
trackers close, and after #584 closes with the documentation pull request, the
expected open counts are 31 pull requests and 63 issues. #450, #403, and #469
are the K-series records intentionally left open. The execution addendum
records the read-back counts.

## Execution addendum

Placeholder. The publication commit replaces this section with closure comment
URLs, read-backs, the documentation commit, and CI evidence.
