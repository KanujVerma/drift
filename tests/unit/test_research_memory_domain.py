"""Unit tests for structured research memory domain models (M6-1, Issue 205)."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.research_memory import (
    RESEARCH_MEMORY_SCHEMA_VERSION,
    FailureCategory,
    FailurePostmortemV1,
    HypothesisLifecycleV1,
    HypothesisStateUpdatedAuditEventPayloadV1,
    HypothesisStatus,
    ParameterSearchSpaceV1,
    PostmortemRecordedAuditEventPayloadV1,
    ResearchTrialRecordV1,
    TrialOutcome,
    TrialRecordedAuditEventPayloadV1,
    build_failure_postmortem,
    build_hypothesis_lifecycle,
    build_parameter_search_space,
    build_research_trial_record,
)
from drift.serialization.canonical import canonical_json

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
HYPOTHESIS_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
HYPOTHESIS_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")
TRIAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd05")
POSTMORTEM_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd06")
SEARCH_SPACE_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd07")
HASH_1 = "a" * 64
HASH_2 = "b" * 64


# =========================================================================
# HypothesisLifecycleV1 Tests
# =========================================================================


def test_hypothesis_lifecycle_valid_creation() -> None:
    lifecycle = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.PROPOSED,
        updated_at=TIMESTAMP,
        notes="Newly formulated momentum hypothesis",
    )
    assert lifecycle.schema_version == RESEARCH_MEMORY_SCHEMA_VERSION
    assert lifecycle.hypothesis_id == HYPOTHESIS_ID_1
    assert lifecycle.status == HypothesisStatus.PROPOSED
    assert lifecycle.notes == "Newly formulated momentum hypothesis"
    assert lifecycle.falsified_at is None
    assert lifecycle.validated_at is None


def test_hypothesis_lifecycle_falsified_requires_evidence() -> None:
    # Missing falsified_at
    with pytest.raises(
        ValidationError, match="falsified status requires a falsified_at timestamp"
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.FALSIFIED,
            updated_at=TIMESTAMP,
            falsification_evidence=(HASH_1,),
            falsified_at=None,
        )

    # Missing falsification_evidence
    with pytest.raises(
        ValidationError, match="falsified status requires falsification evidence"
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.FALSIFIED,
            updated_at=TIMESTAMP,
            falsification_evidence=(),
            falsified_at=TIMESTAMP,
        )

    # Valid falsification
    valid_falsified = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.FALSIFIED,
        updated_at=TIMESTAMP,
        falsification_evidence=(HASH_1,),
        falsified_at=TIMESTAMP,
    )
    assert valid_falsified.status == HypothesisStatus.FALSIFIED
    assert valid_falsified.falsified_at == TIMESTAMP


def test_hypothesis_lifecycle_validated_requires_evidence() -> None:
    # Missing validated_at
    with pytest.raises(
        ValidationError, match="validated status requires a validated_at timestamp"
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.VALIDATED,
            updated_at=TIMESTAMP,
            validation_evidence=(HASH_1,),
            validated_at=None,
        )

    # Missing validation_evidence
    with pytest.raises(
        ValidationError, match="validated status requires validation evidence"
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.VALIDATED,
            updated_at=TIMESTAMP,
            validation_evidence=(),
            validated_at=TIMESTAMP,
        )

    # Valid validation
    valid_validated = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.VALIDATED,
        updated_at=TIMESTAMP,
        validation_evidence=(HASH_1,),
        validated_at=TIMESTAMP,
    )
    assert valid_validated.status == HypothesisStatus.VALIDATED
    assert valid_validated.validated_at == TIMESTAMP


def test_hypothesis_lifecycle_proposed_rejects_timestamps() -> None:
    with pytest.raises(
        ValidationError,
        match="unfalsified hypothesis cannot have a falsified_at timestamp",
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.PROPOSED,
            updated_at=TIMESTAMP,
            falsified_at=TIMESTAMP,
        )

    with pytest.raises(
        ValidationError,
        match="unvalidated hypothesis cannot have a validated_at timestamp",
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.ACTIVE,
            updated_at=TIMESTAMP,
            validated_at=TIMESTAMP,
        )


def test_hypothesis_lifecycle_duplicate_evidence_hashes_rejected() -> None:
    with pytest.raises(
        ValidationError, match="falsification evidence hashes must be unique"
    ):
        build_hypothesis_lifecycle(
            hypothesis_id=HYPOTHESIS_ID_1,
            status=HypothesisStatus.FALSIFIED,
            updated_at=TIMESTAMP,
            falsification_evidence=(HASH_1, HASH_1),
            falsified_at=TIMESTAMP,
        )


def test_hypothesis_lifecycle_hash_mismatch_rejected() -> None:
    valid = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.PROPOSED,
        updated_at=TIMESTAMP,
    )
    data = valid.model_dump(mode="python")
    data["lifecycle_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="hypothesis lifecycle hash mismatch"):
        HypothesisLifecycleV1.model_validate(data)


# =========================================================================
# FailurePostmortemV1 Tests
# =========================================================================


def test_failure_postmortem_valid_creation() -> None:
    postmortem = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        trial_id=TRIAL_ID_1,
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Transaction costs exceeded gross momentum alpha",
        falsified_hypotheses=(HYPOTHESIS_ID_1,),
        evidence_hashes=(HASH_1,),
        lessons_learned="Daily rebalancing generates 400% annualized turnover drag",
        forbidden_variations=("unconstrained daily rebalance",),
        created_at=TIMESTAMP,
    )
    assert postmortem.postmortem_id == POSTMORTEM_ID_1
    assert postmortem.failure_category == FailureCategory.TURNOVER_DRAG
    assert postmortem.forbidden_variations == ("unconstrained daily rebalance",)


def test_failure_postmortem_duplicate_hypotheses_rejected() -> None:
    with pytest.raises(
        ValidationError, match="falsified hypotheses references must be unique"
    ):
        build_failure_postmortem(
            postmortem_id=POSTMORTEM_ID_1,
            experiment_id=EXPERIMENT_ID_1,
            run_id=RUN_ID_1,
            failure_category=FailureCategory.NEGATIVE_ALPHA,
            root_cause_summary="Negative Information Coefficient",
            falsified_hypotheses=(HYPOTHESIS_ID_1, HYPOTHESIS_ID_1),
            lessons_learned="Signal has negative predictive power",
            created_at=TIMESTAMP,
        )


def test_failure_postmortem_duplicate_evidence_rejected() -> None:
    with pytest.raises(ValidationError, match="evidence hashes must be unique"):
        build_failure_postmortem(
            postmortem_id=POSTMORTEM_ID_1,
            experiment_id=EXPERIMENT_ID_1,
            run_id=RUN_ID_1,
            failure_category=FailureCategory.NEGATIVE_ALPHA,
            root_cause_summary="Negative Information Coefficient",
            evidence_hashes=(HASH_1, HASH_1),
            lessons_learned="Signal has negative predictive power",
            created_at=TIMESTAMP,
        )


def test_failure_postmortem_duplicate_forbidden_variations_rejected() -> None:
    with pytest.raises(ValidationError, match="forbidden variations must be unique"):
        build_failure_postmortem(
            postmortem_id=POSTMORTEM_ID_1,
            experiment_id=EXPERIMENT_ID_1,
            run_id=RUN_ID_1,
            failure_category=FailureCategory.NEGATIVE_ALPHA,
            root_cause_summary="Negative Information Coefficient",
            forbidden_variations=("variation_a", "variation_a"),
            lessons_learned="Signal has negative predictive power",
            created_at=TIMESTAMP,
        )


def test_failure_postmortem_hash_mismatch_rejected() -> None:
    valid = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.DRAWDOWN_BREACH,
        root_cause_summary="Max drawdown breached 25%",
        lessons_learned="Risk limit exceeded",
        created_at=TIMESTAMP,
    )
    data = valid.model_dump(mode="python")
    data["postmortem_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="failure postmortem hash mismatch"):
        FailurePostmortemV1.model_validate(data)


# =========================================================================
# ParameterSearchSpaceV1 Tests
# =========================================================================


def test_parameter_search_space_valid_creation() -> None:
    space = build_parameter_search_space(
        search_space_id=SEARCH_SPACE_ID_1,
        strategy_type="momentum_cross_section",
        dimension_names=("lookback_window", "holding_period", "top_k"),
        evaluated_parameter_hashes=(HASH_1, HASH_2),
        total_trials=2,
        exhaustion_fraction=Decimal("0.50"),
        created_at=TIMESTAMP,
    )
    assert space.strategy_type == "momentum_cross_section"
    assert space.total_trials == 2
    assert space.exhaustion_fraction == Decimal("0.50")


def test_parameter_search_space_empty_dimensions_rejected() -> None:
    with pytest.raises(ValidationError, match="dimension_names must not be empty"):
        build_parameter_search_space(
            search_space_id=SEARCH_SPACE_ID_1,
            strategy_type="momentum_cross_section",
            dimension_names=(),
            created_at=TIMESTAMP,
        )


def test_parameter_search_space_duplicate_dimensions_rejected() -> None:
    with pytest.raises(ValidationError, match="dimension_names must be unique"):
        build_parameter_search_space(
            search_space_id=SEARCH_SPACE_ID_1,
            strategy_type="momentum_cross_section",
            dimension_names=("window", "window"),
            created_at=TIMESTAMP,
        )


def test_parameter_search_space_total_trials_bound() -> None:
    with pytest.raises(
        ValidationError,
        match="total_trials cannot be less than evaluated_parameter_hashes count",
    ):
        build_parameter_search_space(
            search_space_id=SEARCH_SPACE_ID_1,
            strategy_type="momentum_cross_section",
            dimension_names=("window",),
            evaluated_parameter_hashes=(HASH_1, HASH_2),
            total_trials=1,  # 1 < 2 evaluated hashes
            created_at=TIMESTAMP,
        )


def test_parameter_search_space_hash_mismatch_rejected() -> None:
    valid = build_parameter_search_space(
        search_space_id=SEARCH_SPACE_ID_1,
        strategy_type="momentum_cross_section",
        dimension_names=("window",),
        created_at=TIMESTAMP,
    )
    data = valid.model_dump(mode="python")
    data["search_space_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="parameter search space hash mismatch"):
        ParameterSearchSpaceV1.model_validate(data)


# =========================================================================
# ResearchTrialRecordV1 Tests
# =========================================================================


def test_research_trial_record_valid_creation() -> None:
    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252, "holding_sessions": 21},
        headline_metrics={
            "sharpe_ratio": "1.45",
            "annualized_return": "0.18",
            "max_drawdown": "0.12",
        },
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    assert trial.trial_id == TRIAL_ID_1
    assert trial.trial_outcome == TrialOutcome.SUPERIOR
    assert isinstance(trial.parameters, Mapping)
    assert trial.parameters["lookback_sessions"] == 252


def test_research_trial_record_parameter_hash_mismatch_rejected() -> None:
    valid = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252},
        headline_metrics={"sharpe_ratio": "1.45"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    data = valid.model_dump(mode="python")
    data["parameters_hash"] = "0" * 64
    with pytest.raises(
        ValidationError,
        match="parameters_hash does not match canonical parameters content hash",
    ):
        ResearchTrialRecordV1.model_validate(data)


def test_research_trial_record_trial_hash_mismatch_rejected() -> None:
    valid = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252},
        headline_metrics={"sharpe_ratio": "1.45"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    data = valid.model_dump(mode="python")
    data["trial_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="research trial hash mismatch"):
        ResearchTrialRecordV1.model_validate(data)


# =========================================================================
# Audit Event Payload & Immutability Tests
# =========================================================================


def test_research_memory_audit_event_payloads() -> None:
    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252},
        headline_metrics={"sharpe_ratio": "1.45"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    trial_payload = TrialRecordedAuditEventPayloadV1(trial=trial)
    assert trial_payload.trial == trial

    postmortem = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.DRAWDOWN_BREACH,
        root_cause_summary="Drawdown breach",
        lessons_learned="Risk bounds exceeded",
        created_at=TIMESTAMP,
    )
    postmortem_payload = PostmortemRecordedAuditEventPayloadV1(postmortem=postmortem)
    assert postmortem_payload.postmortem == postmortem

    lifecycle = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.PROPOSED,
        updated_at=TIMESTAMP,
    )
    lifecycle_payload = HypothesisStateUpdatedAuditEventPayloadV1(lifecycle=lifecycle)
    assert lifecycle_payload.lifecycle == lifecycle


def test_research_memory_canonical_json_roundtrip() -> None:
    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252},
        headline_metrics={"sharpe_ratio": "1.45"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    encoded = canonical_json(trial)
    assert isinstance(encoded, bytes)
    reconstituted = ResearchTrialRecordV1.model_validate_json(encoded)
    assert reconstituted == trial
    assert reconstituted.trial_hash == trial.trial_hash
