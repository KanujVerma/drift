import warnings
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.datasets import DatasetReference, TemporalCoverage
from drift.domain.evidence import (
    ConfidenceState,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
)
from drift.domain.experiments import (
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpecification,
)
from drift.domain.hypotheses import Hypothesis
from drift.domain.strategies import (
    StrategyArtifact,
    StrategyArtifactStatus,
    StrategyReference,
)
from drift.serialization.canonical import canonical_json

HASH = "a" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def valid_artifact_reference(**changes: object) -> ArtifactReference:
    values: dict[str, object] = {
        "artifact_id": uuid7(),
        "kind": ArtifactKind.RESULT,
        "content_hash": HASH,
        "location": "artifacts/result.json",
    }
    values.update(changes)
    return ArtifactReference.model_validate(values)


def valid_hypothesis(**changes: object) -> Hypothesis:
    values: dict[str, object] = {
        "hypothesis_id": uuid7(),
        "created_at": NOW,
        "title": "Momentum persists",
        "statement": "Recent relative strength predicts next-period returns.",
        "mechanism": "Investor underreaction causes delayed price adjustment.",
        "expected_direction": "positive",
        "universe": "US listed common stocks",
        "horizon": "one month",
        "falsification_criteria": "No positive return spread after costs.",
        "parent_hypothesis_ids": (),
        "author_type": "researcher",
        "author_version": "2026.09",
        "tags": ("momentum",),
    }
    values.update(changes)
    return Hypothesis.model_validate(values)


def valid_dataset(**changes: object) -> DatasetReference:
    values: dict[str, object] = {
        "dataset_id": uuid7(),
        "dataset_version": "2026.09.01",
        "schema_version": "1",
        "content_hash": HASH,
        "created_at": NOW,
        "source": "CRSP daily security file",
        "temporal_coverage": TemporalCoverage(started_at=NOW, ended_at=NOW),
        "point_in_time_policy": "Use values known at each observation time.",
        "corporate_action_policy": "Use split and dividend adjusted prices.",
        "availability_timestamp_policy": "Use vendor availability timestamps.",
        "manifest_reference": valid_artifact_reference(kind=ArtifactKind.DATASET),
    }
    values.update(changes)
    return DatasetReference.model_validate(values)


def valid_strategy_reference(**changes: object) -> StrategyReference:
    values: dict[str, object] = {
        "strategy_id": uuid7(),
        "strategy_version": "1.0.0",
        "code_hash": HASH,
        "artifact_reference": valid_artifact_reference(kind=ArtifactKind.STRATEGY),
    }
    values.update(changes)
    return StrategyReference.model_validate(values)


def valid_strategy_artifact(**changes: object) -> StrategyArtifact:
    values: dict[str, object] = {
        "strategy_id": uuid7(),
        "strategy_version": "1.0.0",
        "code_hash": HASH,
        "created_at": NOW,
        "parent_strategy_version": None,
        "hypothesis_ids": (uuid7(),),
        "artifact_reference": valid_artifact_reference(kind=ArtifactKind.STRATEGY),
        "status": StrategyArtifactStatus.RESEARCH,
    }
    values.update(changes)
    return StrategyArtifact.model_validate(values)


def valid_specification(**changes: object) -> ExperimentSpecification:
    values: dict[str, object] = {
        "experiment_id": uuid7(),
        "hypothesis_ids": (uuid7(),),
        "strategy_reference": valid_strategy_reference(),
        "dataset_reference": valid_dataset(),
        "parameters": {"lookback_days": 20},
        "benchmark": "Equal-weighted universe return",
        "evaluation_protocol": {"split": "walk-forward"},
        "cost_assumptions": {"bps": 5},
        "preregistered_metrics": ("sharpe", "max_drawdown"),
        "parent_experiment_ids": (),
        "created_at": NOW,
    }
    values.update(changes)
    return ExperimentSpecification.model_validate(values)


def valid_run(**changes: object) -> ExperimentRun:
    values: dict[str, object] = {
        "run_id": uuid7(),
        "experiment_id": uuid7(),
        "started_at": NOW,
        "completed_at": None,
        "code_hash": HASH,
        "environment_hash": HASH,
        "dataset_hash": HASH,
        "parameters_hash": HASH,
        "status": ExperimentRunStatus.RUNNING,
        "metrics": {"sharpe": 1.2},
        "artifact_references": (),
    }
    values.update(changes)
    return ExperimentRun.model_validate(values)


def valid_evidence(**changes: object) -> EvidenceRecord:
    values: dict[str, object] = {
        "evidence_id": uuid7(),
        "created_at": NOW,
        "claim": "Momentum remained positive after prespecified transaction costs.",
        "evidence_type": EvidenceType.EXPERIMENTAL,
        "supporting_run_ids": (uuid7(),),
        "contradicting_run_ids": (),
        "confidence_state": ConfidenceState.MEDIUM,
        "scope": "US listed common stocks from 2010 through 2025.",
        "supersedes": None,
        "status": EvidenceStatus.TENTATIVE,
    }
    values.update(changes)
    return EvidenceRecord.model_validate(values)


def test_hypothesis_retains_the_approved_provenance_field_matrix() -> None:
    assert {
        "hypothesis_id",
        "created_at",
        "title",
        "statement",
        "mechanism",
        "expected_direction",
        "universe",
        "horizon",
        "falsification_criteria",
        "parent_hypothesis_ids",
        "author_type",
        "author_version",
        "tags",
    } <= set(Hypothesis.model_fields)
    assert {
        "dataset_id",
        "dataset_version",
        "schema_version",
        "content_hash",
        "created_at",
        "source",
        "temporal_coverage",
        "point_in_time_policy",
        "corporate_action_policy",
        "availability_timestamp_policy",
        "manifest_reference",
    } <= set(DatasetReference.model_fields)
    assert {
        "strategy_id",
        "strategy_version",
        "code_hash",
        "created_at",
        "parent_strategy_version",
        "hypothesis_ids",
        "artifact_reference",
        "status",
    } <= set(StrategyArtifact.model_fields)
    assert {
        "experiment_id",
        "hypothesis_ids",
        "strategy_reference",
        "dataset_reference",
        "parameters",
        "benchmark",
        "evaluation_protocol",
        "cost_assumptions",
        "preregistered_metrics",
        "parent_experiment_ids",
        "created_at",
    } <= set(ExperimentSpecification.model_fields)
    assert {
        "run_id",
        "experiment_id",
        "started_at",
        "completed_at",
        "code_hash",
        "environment_hash",
        "dataset_hash",
        "parameters_hash",
        "status",
        "metrics",
        "artifact_references",
        "error_details",
    } <= set(ExperimentRun.model_fields)
    assert {
        "evidence_id",
        "created_at",
        "claim",
        "evidence_type",
        "supporting_run_ids",
        "contradicting_run_ids",
        "confidence_state",
        "scope",
        "supersedes",
        "status",
    } <= set(EvidenceRecord.model_fields)


def test_status_enums_match_the_approved_values() -> None:
    assert {status.value for status in StrategyArtifactStatus} == {
        "research",
        "challenger",
        "approved",
        "retired",
    }
    assert {status.value for status in EvidenceStatus} == {
        "tentative",
        "supported",
        "contradicted",
        "deprecated",
    }


def test_models_are_frozen() -> None:
    hypothesis = valid_hypothesis()

    with pytest.raises(ValidationError):
        hypothesis.title = "changed"


def test_hypothesis_rejects_self_and_duplicate_parent_lineage() -> None:
    hypothesis_id = uuid7()
    with pytest.raises(ValidationError):
        valid_hypothesis(
            hypothesis_id=hypothesis_id,
            parent_hypothesis_ids=(hypothesis_id,),
        )

    parent_id = uuid7()
    with pytest.raises(ValidationError):
        valid_hypothesis(parent_hypothesis_ids=(parent_id, parent_id))


def test_required_text_uuid7_and_lowercase_hashes_are_validated() -> None:
    with pytest.raises(ValidationError):
        valid_hypothesis(author_type="   ")
    with pytest.raises(ValidationError):
        valid_hypothesis(hypothesis_id=UUID("12345678-1234-5678-9234-567812345678"))
    with pytest.raises(ValidationError):
        valid_dataset(content_hash="A" * 64)


def test_timestamps_must_be_aware_and_are_normalized_to_utc() -> None:
    with pytest.raises(ValidationError):
        valid_hypothesis(created_at=datetime(2026, 9, 1, 12))

    hypothesis = valid_hypothesis(
        created_at=datetime(2026, 9, 1, 13, tzinfo=timezone(timedelta(hours=1)))
    )
    assert hypothesis.created_at == NOW


def test_temporal_coverage_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValidationError):
        TemporalCoverage(started_at=NOW, ended_at=NOW - timedelta(microseconds=1))


def test_dataset_and_run_preserve_explicit_versions_hashes_and_references() -> None:
    dataset = valid_dataset()
    run = valid_run()

    assert dataset.dataset_version == "2026.09.01"
    assert dataset.schema_version == "1"
    assert dataset.content_hash == HASH
    assert dataset.manifest_reference.content_hash == HASH
    run_hashes = (
        run.code_hash,
        run.environment_hash,
        run.dataset_hash,
        run.parameters_hash,
    )
    assert run_hashes == (
        HASH,
        HASH,
        HASH,
        HASH,
    )


def test_strategy_artifact_retains_explicit_version_hash_and_hypothesis_lineage() -> (
    None
):
    artifact = valid_strategy_artifact(parent_strategy_version="0.9.0")
    assert artifact.strategy_version == "1.0.0"
    assert artifact.code_hash == HASH
    assert artifact.parent_strategy_version == "0.9.0"

    parent_hypothesis_id = uuid7()
    with pytest.raises(ValidationError):
        valid_strategy_artifact(
            hypothesis_ids=(parent_hypothesis_id, parent_hypothesis_id)
        )


def test_experiment_specification_keeps_lineage_and_rejects_self_parent() -> None:
    hypothesis_ids = (uuid7(), uuid7())
    specification = valid_specification(hypothesis_ids=hypothesis_ids)
    assert specification.hypothesis_ids == hypothesis_ids

    with pytest.raises(ValidationError):
        valid_specification(experiment_id=uuid7(), hypothesis_ids=())

    experiment_id = uuid7()
    with pytest.raises(ValidationError):
        valid_specification(
            experiment_id=experiment_id,
            parent_experiment_ids=(experiment_id,),
        )


def test_json_payloads_are_defensively_frozen_and_model_copy_honors_deep() -> None:
    parameters = {"window": 20, "nested": {"weights": [1, 2]}}
    specification = valid_specification(parameters=parameters)
    parameters["nested"]["weights"].append(3)  # type: ignore[index]

    assert specification.parameters == {"window": 20, "nested": {"weights": (1, 2)}}
    assert isinstance(specification.parameters, MappingProxyType)
    with pytest.raises(TypeError):
        specification.parameters["window"] = 10  # type: ignore[index]

    shallow_copy = specification.model_copy()
    deep_copy = specification.model_copy(deep=True)
    assert shallow_copy.dataset_reference is specification.dataset_reference
    assert deep_copy is not specification
    assert deep_copy.parameters == specification.parameters
    assert deep_copy.dataset_reference is not specification.dataset_reference

    updated_parameters = {"window": [10, 20]}
    updated_copy = specification.model_copy(update={"parameters": updated_parameters})
    updated_parameters["window"].append(30)
    assert updated_copy.parameters == {"window": (10, 20)}


def test_complete_frozen_models_serialize_without_pydantic_warnings() -> None:
    specification = valid_specification(parameters={"nested": ["a", None]})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        serialized = canonical_json(specification)

    assert b'"parameters":{"nested":["a",null]}' in serialized


def test_completed_run_requires_completion_artifact_and_matching_hashes() -> None:
    artifact = valid_artifact_reference()
    completed = valid_run(
        status=ExperimentRunStatus.COMPLETED,
        completed_at=NOW + timedelta(seconds=1),
        artifact_references=(artifact,),
    )
    assert completed.artifact_references == (artifact,)

    with pytest.raises(ValidationError):
        valid_run(status=ExperimentRunStatus.COMPLETED, completed_at=None)
    with pytest.raises(ValidationError):
        valid_run(
            status=ExperimentRunStatus.COMPLETED,
            completed_at=NOW + timedelta(seconds=1),
        )


def test_experiment_run_rejects_completion_before_start() -> None:
    with pytest.raises(ValidationError, match="completion time cannot precede"):
        valid_run(
            status=ExperimentRunStatus.COMPLETED,
            completed_at=NOW - timedelta(microseconds=1),
            artifact_references=(valid_artifact_reference(),),
        )


def test_failed_run_preserves_error_details_and_rejects_stale_errors() -> None:
    failed = valid_run(
        status=ExperimentRunStatus.FAILED,
        completed_at=NOW + timedelta(seconds=1),
        error_details="process exited 2",
    )
    assert failed.error_details == "process exited 2"

    with pytest.raises(ValidationError):
        valid_run(
            status=ExperimentRunStatus.FAILED,
            completed_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        valid_run(error_details="stale failure")


def test_evidence_preserves_supersession_and_rejects_overlapping_run_lineage() -> None:
    superseded_evidence_id = uuid7()
    evidence = valid_evidence(supersedes=superseded_evidence_id)
    assert evidence.supersedes == superseded_evidence_id

    run_id = uuid7()
    with pytest.raises(ValidationError):
        valid_evidence(supporting_run_ids=(run_id,), contradicting_run_ids=(run_id,))
