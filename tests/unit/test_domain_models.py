import warnings
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.datasets import DatasetKind, DatasetReference, TemporalCoverage
from drift.domain.evidence import EvidenceRecord, EvidenceVerdict
from drift.domain.experiments import (
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpecification,
)
from drift.domain.hypotheses import Hypothesis, HypothesisStatus
from drift.domain.strategies import (
    StrategyArtifact,
    StrategyArtifactKind,
    StrategyReference,
)
from drift.serialization.canonical import canonical_json

HASH = "a" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def valid_hypothesis(**changes: object) -> Hypothesis:
    values: dict[str, object] = {
        "hypothesis_id": uuid7(),
        "title": "Momentum persists",
        "statement": "Recent relative strength predicts next-period returns.",
        "rationale": "The relationship is measurable using a fixed universe.",
        "created_at": NOW,
        "status": HypothesisStatus.PROPOSED,
    }
    values.update(changes)
    return Hypothesis.model_validate(values)


def valid_dataset(**changes: object) -> DatasetReference:
    values: dict[str, object] = {
        "dataset_id": uuid7(),
        "name": "Daily prices",
        "version": "2026.09.01",
        "kind": DatasetKind.MARKET_DATA,
        "content_hash": HASH,
        "temporal_coverage": TemporalCoverage(started_at=NOW, ended_at=NOW),
        "fields": ("close", "volume"),
        "created_at": NOW,
    }
    values.update(changes)
    return DatasetReference.model_validate(values)


def valid_strategy(**changes: object) -> StrategyReference:
    values: dict[str, object] = {
        "strategy_id": uuid7(),
        "name": "Relative strength ranking",
        "version": "1.0.0",
        "description": "Ranks a fixed universe by trailing returns.",
        "created_at": NOW,
    }
    values.update(changes)
    return StrategyReference.model_validate(values)


def valid_specification(**changes: object) -> ExperimentSpecification:
    values: dict[str, object] = {
        "specification_id": uuid7(),
        "hypothesis_id": uuid7(),
        "dataset_references": (valid_dataset(),),
        "strategy_reference": valid_strategy(),
        "parameters": {"lookback_days": 20},
        "evaluation_protocol": {"split": "walk-forward"},
        "cost_assumptions": {"bps": 5},
        "created_at": NOW,
    }
    values.update(changes)
    return ExperimentSpecification.model_validate(values)


def valid_run(**changes: object) -> ExperimentRun:
    values: dict[str, object] = {
        "run_id": uuid7(),
        "specification_id": uuid7(),
        "status": ExperimentRunStatus.RUNNING,
        "started_at": NOW,
        "parameters": {"lookback_days": 20},
        "metrics": {"sharpe": 1.2},
    }
    values.update(changes)
    return ExperimentRun.model_validate(values)


def valid_artifact(**changes: object) -> StrategyArtifact:
    values: dict[str, object] = {
        "artifact_id": uuid7(),
        "strategy_id": uuid7(),
        "kind": StrategyArtifactKind.SOURCE,
        "content_hash": HASH,
        "location": "artifacts/strategy.py",
        "created_at": NOW,
    }
    values.update(changes)
    return StrategyArtifact.model_validate(values)


def test_models_are_frozen() -> None:
    hypothesis = valid_hypothesis()

    with pytest.raises(ValidationError):
        hypothesis.title = "changed"


def test_hypothesis_cannot_reference_itself() -> None:
    hypothesis_id = uuid7()

    with pytest.raises(ValidationError):
        valid_hypothesis(
            hypothesis_id=hypothesis_id,
            parent_hypothesis_ids=(hypothesis_id,),
        )


def test_hypothesis_parent_references_must_be_unique() -> None:
    parent_id = uuid7()

    with pytest.raises(ValidationError):
        valid_hypothesis(parent_hypothesis_ids=(parent_id, parent_id))


def test_domain_identifiers_must_be_uuid7() -> None:
    with pytest.raises(ValidationError):
        valid_hypothesis(hypothesis_id=UUID("12345678-1234-5678-9234-567812345678"))


def test_required_text_is_nonblank_and_hashes_are_lowercase_sha256() -> None:
    with pytest.raises(ValidationError):
        valid_dataset(name="   ")

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


def test_dataset_fields_are_nonempty_and_unique() -> None:
    with pytest.raises(ValidationError):
        valid_dataset(fields=())

    with pytest.raises(ValidationError):
        valid_dataset(fields=("close", "close"))


def test_experiment_dataset_references_are_nonempty_and_unique() -> None:
    with pytest.raises(ValidationError):
        valid_specification(dataset_references=())

    dataset = valid_dataset()
    with pytest.raises(ValidationError):
        valid_specification(dataset_references=(dataset, dataset))


def test_json_payloads_are_defensively_frozen() -> None:
    parameters = {"window": 20, "nested": {"weights": [1, 2]}}
    specification = valid_specification(parameters=parameters)

    parameters["nested"]["weights"].append(3)  # type: ignore[index]

    assert specification.parameters == {
        "window": 20,
        "nested": {"weights": (1, 2)},
    }
    assert isinstance(specification.parameters, MappingProxyType)
    with pytest.raises(TypeError):
        specification.parameters["window"] = 10  # type: ignore[index]


def test_model_copy_revalidates_json_payloads() -> None:
    parameters = {"nested": [1, 2]}
    specification = valid_specification().model_copy(
        update={"parameters": parameters}
    )

    parameters["nested"].append(3)

    assert specification.parameters == {"nested": (1, 2)}
    assert isinstance(specification.parameters, MappingProxyType)


def test_frozen_json_payloads_remain_canonically_serializable() -> None:
    specification = valid_specification(parameters={"nested": ["a", None]})

    assert canonical_json(specification.parameters) == b'{"nested":["a",null]}'


def test_complete_frozen_models_serialize_without_pydantic_warnings() -> None:
    specification = valid_specification(parameters={"nested": ["a", None]})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        serialized = canonical_json(specification)

    assert b'"parameters":{"nested":["a",null]}' in serialized


def test_completed_run_requires_completion_time() -> None:
    with pytest.raises(ValidationError):
        valid_run(status=ExperimentRunStatus.COMPLETED, completed_at=None)


def test_failed_run_preserves_error_details() -> None:
    run = valid_run(
        status=ExperimentRunStatus.FAILED,
        completed_at=NOW + timedelta(seconds=1),
        error_details="process exited 2",
    )

    assert run.error_details == "process exited 2"


def test_failed_run_requires_error_details_and_finished_runs_require_valid_times(
) -> None:
    with pytest.raises(ValidationError):
        valid_run(
            status=ExperimentRunStatus.FAILED,
            completed_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(ValidationError):
        valid_run(
            status=ExperimentRunStatus.COMPLETED,
            completed_at=NOW - timedelta(microseconds=1),
        )


def test_non_failed_run_cannot_include_error_details() -> None:
    with pytest.raises(ValidationError):
        valid_run(error_details="stale failure")


def test_artifact_and_evidence_references_preserve_content_hashes() -> None:
    artifact = valid_artifact()
    reference = ArtifactReference(
        artifact_id=artifact.artifact_id,
        kind=ArtifactKind.STRATEGY,
        content_hash=artifact.content_hash,
        location=artifact.location,
    )
    evidence = EvidenceRecord(
        evidence_id=uuid7(),
        experiment_run_id=uuid7(),
        verdict=EvidenceVerdict.SUPPORTS,
        summary="The pre-registered measurement supported the hypothesis.",
        artifact_references=(reference,),
        recorded_at=NOW,
    )

    assert evidence.artifact_references[0].content_hash == HASH


def test_evidence_requires_unique_artifact_references() -> None:
    reference = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.RESULT,
        content_hash=HASH,
        location="artifacts/results.json",
    )

    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id=uuid7(),
            experiment_run_id=uuid7(),
            verdict=EvidenceVerdict.INCONCLUSIVE,
            summary="The measurement was inconclusive.",
            artifact_references=(reference, reference),
            recorded_at=NOW,
        )
