"""Unrun source-backed E6B research association tests for issue #540.

These exercise accepted E1 and K1 objects but do not authenticate original
scheduler grants, Matthew's provisioner or independent validator retention.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    DataWindowV1,
    DecisionScheduleV1,
    PrimaryComparisonV1,
    RunAccountBindingV1,
    ScoringWindowV1,
    SessionWindowV1,
    build_arm_spec,
    build_campaign_spec,
    build_run_account_binding,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    build_stage1_trial_provenance_snapshot,
)
from drift.intelligence.contracts import (
    ArtifactReference,
    ResearchCandidate,
    ResearchContext,
    StoredArtifactRef,
    compute_record_hash,
)
from drift.intelligence.e1_trial_association import (
    VALIDATION_CANDIDATE_PROFILE,
    append_local_validation_original,
    build_retained_validation_candidate,
    readback_local_validation_original,
    review_research_e1_binding,
)
from drift.intelligence.receipts import (
    create_cost_receipt,
    create_started_attempt,
    create_terminal_attempt,
)
from drift.intelligence.validation import ValidationResult
from drift.ledger.sqlite import SQLiteLedger
from drift.serialization.canonical import content_hash

T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
SHA = "a" * 64


def original_utc_text(moment: datetime) -> str:
    """Match repository canonical_json datetime spelling before source hashing."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def e1_originals() -> tuple[
    CampaignSpecV1,
    tuple[ArmSpecV1, ...],
    tuple[RunAccountBindingV1, ...],
    tuple[str, ...],
    Stage1TrialProvenanceSnapshotV1,
]:
    arms = (
        build_arm_spec(
            arm_id="ARM-B", campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=["B3", "B4", "B5"],
            initial_strategy_reference="B3", initial_capital="10000",
            currency="USD", arm_account_role="PRIMARY_TEST",
            mandate_reference="fixture://balanced-mandate-v1",
            execution_policy_reference="fixture://next-open-v1",
            research_budget_reference="fixture://budget-B",
            information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
            feedback_policy_reference="fixture://matured-own-arm-v1",
            model_configuration_reference="fixture://model-B-v1",
            deterministic_seed_reference="fixture://seed-B-001",
            frozen_configuration_reference="b" * 64,
        ),
        build_arm_spec(
            arm_id="ARM-R", campaign_id="CAMP-E1-SYNTH-001",
            selector_type="DETERMINISTIC_COMPARATOR",
            eligible_strategy_references=["B3", "B4", "B5"],
            initial_strategy_reference="B3", initial_capital="10000",
            currency="USD", arm_account_role="COMPARATOR",
            mandate_reference="fixture://balanced-mandate-v1",
            execution_policy_reference="fixture://next-open-v1",
            research_budget_reference="fixture://budget-R",
            information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
            feedback_policy_reference="fixture://matured-own-arm-v1",
            model_configuration_reference="NONE",
            deterministic_seed_reference="fixture://seed-R-001",
            frozen_configuration_reference="b" * 64,
        ),
    )
    campaign = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1(
            test_arm_id="ARM-B", comparator_arm_id="ARM-R",
        ),
        control_arm_references=[],
        arm_spec_references=[arm.arm_spec_fingerprint for arm in arms],
        qualified_dataset_references=[],
        data_window=DataWindowV1(
            start_date="2024-01-02", end_date="2026-01-30",
            calendar_id="fixture://calendar-v1",
        ),
        warmup_window=SessionWindowV1(sessions_count=253),
        observation_window=SessionWindowV1(sessions_count=126),
        scoring_window=ScoringWindowV1(
            start_session="SC-001", end_session="SC-021",
            fresh_accounts=True,
        ),
        decision_schedule=DecisionScheduleV1(
            frequency="MONTHLY",
            alignment="LAST_COMPLETED_SESSION",
            execution_timing="NEXT_OPEN",
        ),
        allowed_strategy_families=["B3", "B4", "B5"],
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={
            "synthetic_fixture_only": True,
            "reviewer_receipts": [],
        },
    )
    bindings = tuple(
        build_run_account_binding(
            campaign_id=campaign.campaign_id,
            run_id="RUN-001", arm_id=arm.arm_id,
            portfolio_account_id=f"SYNTH-ACC-{arm.arm_id[-1]}-001",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        )
        for arm in arms
    )
    run_ids = ("RUN-001",)
    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=campaign, arms=arms, bindings=bindings,
        expected_run_ids=run_ids,
        run_id="RUN-001", arm_id="ARM-B", checkpoint_id="CKPT-001",
        events=(),
    )
    return campaign, arms, bindings, run_ids, snapshot


def fixture(disposition: str = "propose", *, failure: bool = False,
            unknown_cost: bool = False) -> dict[str, Any]:
    campaign, arms, bindings, run_ids, original_e1 = e1_originals()
    existing = json.loads(
        Path("tests/fixtures/adaptive_research/research_v1.json")
        .read_text(encoding="utf-8")
    )["fixtures"]
    context_dict = dict(existing["F01"])
    context_dict["scope"] = {
        "experiment_id": "fixture:study",
        "arm_id": "ARM-B",
        "account_id": "SYNTH-ACC-B-001",
        "campaign_ref": {
            "id": campaign.campaign_id, "version": "fixture-1",
            "sha256": campaign.campaign_spec_fingerprint,
        },
    }
    context_dict.update({
        "decision_cutoff": original_utc_text(T0),
        "memory_cutoff": original_utc_text(T0),
        "built_at": original_utc_text(T0 + timedelta(seconds=1)),
        "review_started_at": original_utc_text(T0 + timedelta(seconds=2)),
    })
    context_dict["record_hash"] = compute_record_hash(context_dict)
    context = ResearchContext.model_validate(context_dict)
    context_ref = ArtifactReference(
        id=context.context_id, version="drift-research/1-draft",
        sha256=context.record_hash,
    )
    started = create_started_attempt(
        attempt_id="synthetic-attempt-B",
        logical_request_id="synthetic-logical-request-B",
        attempt_event_id="synthetic-attempt-event-0",
        scope=context.scope, context_ref=context_ref,
        method_ref=context.method_ref, budget_ref=context.budget_ref,
        producer="scripted_fixture",
        started_at=T0 + timedelta(seconds=3),
    )
    candidate = None
    validation = None
    receipt = None
    costs = ()
    if not failure:
        raw = dict(existing["F02"])
        raw.update({
            "attempt_id": started.attempt_id,
            "scope": context.scope.model_dump(mode="python"),
            "context_ref": context_ref.model_dump(mode="python"),
            "completed_at": original_utc_text(T0 + timedelta(seconds=5)),
            "valid_until": original_utc_text(T0 + timedelta(minutes=1)),
            "cost_receipt_ids": (),
        })
        if disposition != "propose":
            raw["disposition"] = disposition
            raw["strategy"] = None
            raw["targets"] = []
            raw["cash_weight"] = None
            raw["reason_codes"] = [f"reason-{disposition}"]
        raw["record_hash"] = compute_record_hash(raw)
        candidate = ResearchCandidate.model_validate(raw)
        validation = ValidationResult(
            is_valid=True, status="VALID", reason="synthetic valid",
            candidate=candidate,
        )
        receipt = build_retained_validation_candidate(
            validation_id="retained-validation-1",
            attempt_id=started.attempt_id,
            original_validation=validation,
            raw_output_ref=StoredArtifactRef(
                artifact_id="raw-output", kind="fixture",
                content_hash=SHA, location="fixture://raw-output",
            ),
            original_validation_ref=StoredArtifactRef(
                artifact_id="retained-validation", kind="fixture",
                content_hash=content_hash(validation.model_dump(mode="python")),
                location="fixture://validation",
            ),
            validator_issuer_ref=ArtifactReference(
                id="untrusted-research-validator", version="fixture-1",
                sha256=SHA,
            ),
            first_available_at=T0 + timedelta(seconds=6),
        )
    if unknown_cost:
        cost = create_cost_receipt(
            receipt_id="cost-unknown",
            scope=context.scope, category="inference",
            billing_identity="mock-billing",
            amount_basis="unknown", unknown_reason="provider incomplete",
            attempt_id=started.attempt_id,
            recorded_at=T0 + timedelta(seconds=6),
        )
        costs = (cost,)
        if candidate is not None:
            modified = candidate.model_dump(mode="python")
            modified["cost_receipt_ids"] = (cost.receipt_id,)
            modified["record_hash"] = compute_record_hash(modified)
            candidate = ResearchCandidate.model_validate(modified)
            validation = ValidationResult(
                is_valid=True, status="VALID", reason="synthetic valid",
                candidate=candidate,
            )
            receipt = build_retained_validation_candidate(
                validation_id="retained-validation-1",
                attempt_id=started.attempt_id,
                original_validation=validation,
                raw_output_ref=StoredArtifactRef(
                    artifact_id="raw-output", kind="fixture",
                    content_hash=SHA, location="fixture://raw-output",
                ),
                original_validation_ref=StoredArtifactRef(
                    artifact_id="retained-validation", kind="fixture",
                    content_hash=content_hash(validation.model_dump(mode="python")),
                    location="fixture://validation",
                ),
                validator_issuer_ref=ArtifactReference(
                    id="untrusted-research-validator",
                    version="fixture-1", sha256=SHA,
                ),
                first_available_at=T0 + timedelta(seconds=6),
            )
    terminal = create_terminal_attempt(
        prior_attempt=started,
        attempt_event_id="synthetic-attempt-event-1",
        completed_at=T0 + timedelta(seconds=7),
        status="failed" if failure else "completed",
        validation_ref=(
            ArtifactReference(
                id=receipt.validation_id,
                version=VALIDATION_CANDIDATE_PROFILE,
                sha256=receipt.record_hash,
            ) if receipt is not None else None
        ),
        candidate_ref=(
            ArtifactReference(
                id=candidate.candidate_id,
                version="drift-research/1-draft",
                sha256=candidate.record_hash,
            ) if candidate is not None else None
        ),
        cost_receipt_ids=tuple(cost.receipt_id for cost in costs),
        reason_codes=("provider_timeout",) if failure else (),
        failure_artifact_ref=(
            ArtifactReference(
                id="failed-original", version="fixture-1", sha256=SHA,
            ) if failure else None
        ),
    )
    return {
        "campaign": campaign, "arms": arms, "bindings": bindings,
        "expected_run_ids": run_ids, "provenance": original_e1,
        "context": context, "started": started, "terminal": terminal,
        "validation": validation, "retained_validation": receipt,
        "candidate": candidate, "replay": None, "costs": costs,
        "logical_request_id": started.logical_request_id,
        "decision_deadline": T0 + timedelta(seconds=9),
        "association_first_available_at": T0 + timedelta(seconds=10),
    }


def _assert_refusal(inputs: dict[str, Any], code: str) -> None:
    result = review_research_e1_binding(**inputs)
    assert not result.structural_consistency
    assert result.candidate_association_hash is None
    assert code in result.source_refusal_reasons
    assert not result.original_issuer_verified
    assert not result.admitted_for_e6b_or_trading


def test_actual_k1_e1_source_check_is_gated_not_fake_issuer() -> None:
    data = fixture()
    result = review_research_e1_binding(**data)
    assert result.structural_consistency
    assert result.candidate_association_hash is not None
    assert result.observed_disposition == "propose"
    assert "MISSING_MATTHEW_ORIGINAL_ACCOUNT_ISSUER_508" in (
        result.missing_trusted_producers
    )
    assert "MISSING_KANUJ_ORIGINAL_SCHEDULER_ISSUER_512" in (
        result.missing_trusted_producers
    )
    assert not result.original_issuer_verified
    assert not result.admitted_for_e6b_or_trading


def test_same_original_records_replay_same_candidate_hash_without_score() -> None:
    data = fixture()
    a = review_research_e1_binding(**data)
    b = review_research_e1_binding(**data)
    assert a == b
    assert a.candidate_association_hash == b.candidate_association_hash
    assert not a.admitted_for_e6b_or_trading


@pytest.mark.parametrize("disposition", ["hold", "abstain", "unavailable"])
def test_distinct_valid_non_trading_candidate_outcomes(disposition: str) -> None:
    result = review_research_e1_binding(**fixture(disposition))
    assert result.structural_consistency
    assert result.observed_disposition == disposition
    assert not result.admitted_for_e6b_or_trading
    if disposition == "hold":
        assert "MISSING_VERIFIED_MATCHING_INCUMBENT_FOR_HOLD" in (
            result.missing_trusted_producers
        )


def test_original_failed_attempt_stays_in_denominator_without_candidate() -> None:
    result = review_research_e1_binding(**fixture(failure=True))
    assert result.structural_consistency
    assert result.observed_disposition is None
    assert not result.admitted_for_e6b_or_trading


def test_unknown_research_cost_is_not_verified_zero() -> None:
    result = review_research_e1_binding(**fixture(unknown_cost=True))
    assert result.structural_consistency
    assert len(result.included_cost_receipt_hashes) == 1
    assert not result.admitted_for_e6b_or_trading


def test_wrong_E1_account_or_wrong_arm_refuses() -> None:
    data = fixture()
    context = data["context"]
    data["context"] = context.model_copy(
        update={"scope": context.scope.model_copy(
            update={"account_id": "SYNTH-ACC-R-001"},
        )}
    )
    _assert_refusal(data, "K1_SOURCE_OR_TIMESTAMP_INVALID:ValidationError")
    data = fixture()
    scope = data["provenance"].scope
    data["provenance"] = replace(
        data["provenance"],
        scope=replace(scope, run_id="RUN-002"),
    )
    result = review_research_e1_binding(**data)
    assert not result.structural_consistency
    assert result.source_refusal_reasons[0].startswith(
        "E1_MANIFEST_OR_PROVENANCE_INVALID:"
    )


def test_wrong_checkpoint_or_full_manifest_does_not_pass_rehash() -> None:
    data = fixture()
    scope = data["provenance"].scope
    data["provenance"] = replace(
        data["provenance"],
        scope=replace(scope, checkpoint_id="CKPT-OTHER"),
    )
    assert not review_research_e1_binding(**data).structural_consistency
    data = fixture()
    scope = data["provenance"].scope
    data["provenance"] = replace(
        data["provenance"],
        scope=replace(scope, complete_manifest_fingerprint="f" * 64),
    )
    assert not review_research_e1_binding(**data).structural_consistency


def test_late_terminal_after_decision_deadline_refuses() -> None:
    data = fixture()
    data["decision_deadline"] = T0 + timedelta(seconds=6)
    _assert_refusal(data, "TERMINAL_AFTER_DECISION_DEADLINE")


def test_bad_raw_validation_digest_does_not_claim_original_retention() -> None:
    data = fixture()
    receipt = data["retained_validation"]
    data["retained_validation"] = replace(
        receipt, record_hash="f" * 64,
    )
    _assert_refusal(data, "INVALID_RETAINED_VALIDATION")


def test_unretained_validation_original_ref_is_not_canonical_bytes() -> None:
    data = fixture()
    val = data["validation"]
    with pytest.raises(ValueError, match="ORIGINAL_VALIDATION_BYTES_HASH_MISMATCH"):
        build_retained_validation_candidate(
            validation_id="bad-original", attempt_id=data["started"].attempt_id,
            original_validation=val,
            raw_output_ref=StoredArtifactRef(
                artifact_id="raw", kind="fixture", content_hash=SHA,
                location="fixture://raw",
            ),
            original_validation_ref=StoredArtifactRef(
                artifact_id="wrong-decision", kind="fixture",
                content_hash="f" * 64, location="fixture://wrong",
            ),
            validator_issuer_ref=ArtifactReference(
                id="not-authority", version="fixture-1", sha256=SHA,
            ),
            first_available_at=T0 + timedelta(seconds=6),
        )


def test_absent_original_validation_is_not_admitted() -> None:
    data = fixture()
    data["retained_validation"] = None
    _assert_refusal(data, "ORIGINAL_VALIDATION_MISSING")


def test_wrong_logical_request_and_modified_candidate_ref_refuse() -> None:
    data = fixture()
    data["logical_request_id"] = "another-request"
    _assert_refusal(data, "WRONG_LOGICAL_REQUEST")
    data = fixture()
    data["candidate"] = None
    _assert_refusal(data, "FAILED_ATTEMPT_MUST_NOT_MINT_CANDIDATE")


def test_original_context_is_revalidated_against_forged_future_input() -> None:
    data = fixture()
    context = data["context"]
    data["context"] = context.model_copy(
        update={"decision_cutoff": T0 - timedelta(days=2)}
    )
    _assert_refusal(data, "K1_SOURCE_OR_TIMESTAMP_INVALID:ValidationError")


def test_bogus_original_inference_validation_receipt_cannot_be_valid() -> None:
    data = fixture()
    receipt = data["retained_validation"]
    data["retained_validation"] = replace(
        receipt, first_available_at=T0 + timedelta(seconds=15),
    )
    _assert_refusal(data, "INVALID_RETAINED_VALIDATION")


def test_claimed_issuer_references_change_candidate_hash_not_admission() -> None:
    data = fixture()
    original = review_research_e1_binding(**data)
    data["original_scheduler_grant_ref"] = ArtifactReference(
        id="unverified-grant", version="proposed-1", sha256="c" * 64,
    )
    data["original_account_provisioning_ref"] = ArtifactReference(
        id="unverified-original-book", version="proposed-1", sha256="d" * 64,
    )
    with_unverified_claims = review_research_e1_binding(**data)
    assert original.structural_consistency
    assert with_unverified_claims.structural_consistency
    assert original.candidate_association_hash != (
        with_unverified_claims.candidate_association_hash
    )
    assert not with_unverified_claims.original_issuer_verified
    assert not with_unverified_claims.admitted_for_e6b_or_trading


def test_validation_failure_cannot_carry_valid_candidate() -> None:
    data = fixture()
    real_validated = data["validation"]
    forged = real_validated.model_copy(
        update={"status": "REJECTED", "is_valid": False}
    )
    with pytest.raises(ValueError, match="FAILURE_CANNOT_CARRY_CANDIDATE"):
        build_retained_validation_candidate(
            validation_id="forged-rejection",
            attempt_id=data["started"].attempt_id,
            original_validation=forged,
            raw_output_ref=StoredArtifactRef(
                artifact_id="raw", kind="fixture", content_hash=SHA,
                location="fixture://raw",
            ),
            original_validation_ref=StoredArtifactRef(
                artifact_id="decision", kind="fixture",
                content_hash=content_hash(forged.model_dump(mode="python")),
                location="fixture://decision",
            ),
            validator_issuer_ref=ArtifactReference(
                id="label-only", version="proposed-1", sha256=SHA,
            ),
            first_available_at=T0 + timedelta(seconds=6),
        )


def test_actual_sqlite_ledger_records_and_replays_rejected_original(
    tmp_path: Path,
) -> None:
    path = tmp_path / "k1-original.db"
    ledger = SQLiteLedger(path)
    issued = T0 + timedelta(seconds=6)
    original = ValidationResult(
        is_valid=False, status="REJECTED",
        reason="synthetic source lacks required input", candidate=None,
    )
    issued_receipt = append_local_validation_original(
        ledger=ledger, event_id=uuid7(), entity_id=uuid7(),
        observed_at=issued, validation_id="original-validation-rejection",
        attempt_id="original-attempt",
        original_validation=original,
        raw_output_bytes=b'{"invalid":"source"}',
        issuer_claim=ArtifactReference(
            id="untrusted-validator-issuer", version="candidate-1",
            sha256=SHA,
        ),
    )
    assert issued_receipt.candidate.status == "REJECTED"
    assert issued_receipt.candidate.candidate_ref is None
    assert issued_receipt.audit_event_hash
    assert issued_receipt.raw_output_bytes_sha256 is not None
    reopened = SQLiteLedger.open_existing(path)
    reread = readback_local_validation_original(
        ledger=reopened,
        event_id=issued_receipt.audit_event_id,
        expected_event_hash=issued_receipt.audit_event_hash,
    )
    assert reread == issued_receipt
    assert not reread.trusted_research_issuer_authenticated
    assert not reread.can_admit_e6b


def test_actual_sqlite_ledger_preserves_valid_candidate_original(
    tmp_path: Path,
) -> None:
    data = fixture()
    path = tmp_path / "original-validation.db"
    ledger = SQLiteLedger(path)
    record = append_local_validation_original(
        ledger=ledger, event_id=uuid7(), entity_id=uuid7(),
        observed_at=T0 + timedelta(seconds=6),
        validation_id="valid-original",
        attempt_id=data["started"].attempt_id,
        original_validation=data["validation"],
        raw_output_bytes=b'{"disposition":"propose"}',
        issuer_claim=ArtifactReference(
            id="untrusted-original-issuer", version="candidate-1",
            sha256=SHA,
        ),
    )
    assert record.candidate.status == "VALID"
    assert record.candidate.candidate_ref is not None
    assert record.candidate.candidate_ref.id == data["candidate"].candidate_id
    assert not record.trusted_research_issuer_authenticated


def test_replayed_validation_id_is_unique_not_double_issued(
    tmp_path: Path,
) -> None:
    from drift.errors import DuplicateEventError

    ledger = SQLiteLedger(tmp_path / "dedupe.db")
    kw: dict[str, Any] = {
        "ledger": ledger, "entity_id": uuid7(),
        "observed_at": T0 + timedelta(seconds=6),
        "validation_id": "same-original-validation-id",
        "attempt_id": "same-original-attempt",
        "original_validation": ValidationResult(
            is_valid=False, status="INVALID", reason="invalid source",
            candidate=None,
        ),
        "raw_output_bytes": b'{"reason":"failure"}',
        "issuer_claim": ArtifactReference(
            id="mock-issuer", version="candidate-1", sha256=SHA,
        ),
    }
    append_local_validation_original(event_id=uuid7(), **kw)
    with pytest.raises(DuplicateEventError):
        append_local_validation_original(event_id=uuid7(), **kw)


def test_original_ledger_expected_event_hash_cannot_be_substituted(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "original.db")
    original = append_local_validation_original(
        ledger=ledger, event_id=uuid7(), entity_id=uuid7(),
        observed_at=T0 + timedelta(seconds=6),
        validation_id="unique-rejected", attempt_id="attempt",
        original_validation=ValidationResult(
            is_valid=False, status="REJECTED",
            reason="synthetic missing input", candidate=None,
        ),
        raw_output_bytes=b'{"missing":"input"}',
        issuer_claim=ArtifactReference(
            id="not-an-issuer-proof", version="candidate-1", sha256=SHA,
        ),
    )
    with pytest.raises(ValueError, match="EVENT_BINDING_MISMATCH"):
        readback_local_validation_original(
            ledger=ledger, event_id=original.audit_event_id,
            expected_event_hash="f" * 64,
        )
    with pytest.raises(ValueError, match="NOT_UNIQUE_OR_MISSING"):
        readback_local_validation_original(
            ledger=SQLiteLedger(tmp_path / "other-ledger.db"),
            event_id=original.audit_event_id,
            expected_event_hash=original.audit_event_hash,
        )


def test_original_validation_raw_cannot_exceed_bounded_retention(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "too-big.db")
    with pytest.raises(ValueError, match="ORIGINAL_RAW_NOT_BOUNDED_BYTES"):
        append_local_validation_original(
            ledger=ledger, event_id=uuid7(), entity_id=uuid7(),
            observed_at=T0 + timedelta(seconds=6),
            validation_id="too-large", attempt_id="attempt",
            original_validation=ValidationResult(
                is_valid=False, status="REFUSED",
                reason="synthetic rejection", candidate=None,
            ),
            raw_output_bytes=b"x" * 1_048_577,
            issuer_claim=ArtifactReference(
                id="not-an-issuer", version="candidate-1", sha256=SHA,
            ),
        )
    assert ledger.verified_events() == ()


def test_original_rejected_with_no_raw_still_keeps_rejection_reason(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "rejection-without-response.db")
    rec = append_local_validation_original(
        ledger=ledger, event_id=uuid7(), entity_id=uuid7(),
        observed_at=T0 + timedelta(seconds=6),
        validation_id="no-response", attempt_id="attempt",
        original_validation=ValidationResult(
            is_valid=False, status="REFUSED",
            reason="request never dispatched", candidate=None,
        ),
        raw_output_bytes=None,
        issuer_claim=ArtifactReference(
            id="not-an-issuer", version="candidate-1", sha256=SHA,
        ),
    )
    assert rec.candidate.raw_output_ref is None
    assert rec.candidate.status == "REFUSED"
    assert rec.raw_output_bytes_sha256 is None
    assert not rec.can_admit_e6b
