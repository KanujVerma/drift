"""Unit tests for M2 evaluation lane admission contracts and discriminator."""

from typing import Literal, get_args, get_origin

import pytest
from pydantic import TypeAdapter, ValidationError

import drift.domain.evaluator_lanes as lanes_module
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ALPACA_LIMITATION_TRUNCATED_CA,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
    promotion_evaluation_admission_hash,
)

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def test_exploratory_admission_valid_and_hash_verification() -> None:
    limitations = (
        ALPACA_LIMITATION_BOUNDED_COHORT,
        ALPACA_LIMITATION_ABSENT_HALTS,
    )
    unhashed = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=limitations,
        admission_hash=H0,
    )
    expected_hash = exploratory_evaluation_admission_hash(unhashed)
    admission = unhashed.model_copy(update={"admission_hash": expected_hash})

    assert admission.lane == "exploratory"
    assert admission.schema_version == "1"
    assert admission.input_bundle_hash == H1
    assert admission.acknowledged_limitations == limitations
    assert admission.admission_hash == expected_hash


def test_exploratory_admission_tampered_hash_rejected() -> None:
    limitations = (ALPACA_LIMITATION_BOUNDED_COHORT,)
    with pytest.raises(ValidationError, match="admission hash mismatch"):
        ExploratoryEvaluationAdmissionV1(
            schema_version="1",
            lane="exploratory",
            input_bundle_hash=H1,
            acknowledged_limitations=limitations,
            admission_hash=H2,
        )


def test_exploratory_admission_empty_limitations_rejected() -> None:
    unhashed = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=(),
        admission_hash=H0,
    )
    h = exploratory_evaluation_admission_hash(unhashed)
    with pytest.raises(
        ValidationError, match="acknowledged_limitations must not be empty"
    ):
        ExploratoryEvaluationAdmissionV1(
            schema_version="1",
            lane="exploratory",
            input_bundle_hash=H1,
            acknowledged_limitations=(),
            admission_hash=h,
        )


def test_exploratory_admission_duplicate_limitations_rejected() -> None:
    dups = (ALPACA_LIMITATION_BOUNDED_COHORT, ALPACA_LIMITATION_BOUNDED_COHORT)
    unhashed = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=dups,
        admission_hash=H0,
    )
    h = exploratory_evaluation_admission_hash(unhashed)
    with pytest.raises(ValidationError, match="unique"):
        ExploratoryEvaluationAdmissionV1(
            schema_version="1",
            lane="exploratory",
            input_bundle_hash=H1,
            acknowledged_limitations=dups,
            admission_hash=h,
        )


def test_exploratory_admission_unsorted_limitations_rejected() -> None:
    unsorted_limits = (
        ALPACA_LIMITATION_ABSENT_HALTS,
        ALPACA_LIMITATION_UNVERSIONED_BARS,
    )
    assert unsorted_limits != tuple(sorted(unsorted_limits))
    unhashed = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=unsorted_limits,
        admission_hash=H0,
    )
    h = exploratory_evaluation_admission_hash(unhashed)
    with pytest.raises(ValidationError, match="canonically sorted"):
        ExploratoryEvaluationAdmissionV1(
            schema_version="1",
            lane="exploratory",
            input_bundle_hash=H1,
            acknowledged_limitations=unsorted_limits,
            admission_hash=h,
        )


def test_exploratory_admission_frozen_and_bundle_hash_participates() -> None:
    limitations = (ALPACA_LIMITATION_BOUNDED_COHORT,)
    unhashed_1 = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=limitations,
        admission_hash=H0,
    )
    h1 = exploratory_evaluation_admission_hash(unhashed_1)
    adm_1 = unhashed_1.model_copy(update={"admission_hash": h1})

    unhashed_2 = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H2,
        acknowledged_limitations=limitations,
        admission_hash=H0,
    )
    h2 = exploratory_evaluation_admission_hash(unhashed_2)
    assert h1 != h2

    with pytest.raises(ValidationError):
        adm_1.input_bundle_hash = H2


def test_promotion_admission_valid_and_hash_verification() -> None:
    unhashed = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash=H1,
        m1e_profile_set_hash=H2,
        decision_handoff_hash=H3,
        audit_handoff_hash=H4,
        input_bundle_hash=H1,
        provenance_proof_hash=H3,
        admission_hash=H0,
    )
    expected_hash = promotion_evaluation_admission_hash(unhashed)
    admission = unhashed.model_copy(update={"admission_hash": expected_hash})

    assert admission.lane == "promotion"
    assert admission.schema_version == "1"
    assert admission.m1e_completion_record_hash == H1
    assert admission.m1e_profile_set_hash == H2
    assert admission.decision_handoff_hash == H3
    assert admission.audit_handoff_hash == H4
    assert admission.input_bundle_hash == H1
    assert admission.provenance_proof_hash == H3
    assert admission.admission_hash == expected_hash


def test_promotion_admission_tampered_hash_rejected() -> None:
    with pytest.raises(ValidationError, match="admission hash mismatch"):
        PromotionEvaluationAdmissionV1(
            schema_version="1",
            lane="promotion",
            m1e_completion_record_hash=H1,
            m1e_profile_set_hash=H2,
            decision_handoff_hash=H3,
            audit_handoff_hash=H4,
            input_bundle_hash=H1,
            provenance_proof_hash=H3,
            admission_hash=H2,
        )


def test_admission_discriminator_serialization() -> None:
    adapter: TypeAdapter[EvaluationAdmissionV1] = TypeAdapter(EvaluationAdmissionV1)

    exp_unhashed = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,),
        admission_hash=H0,
    )
    exp_hash = exploratory_evaluation_admission_hash(exp_unhashed)
    exp_admission = exp_unhashed.model_copy(update={"admission_hash": exp_hash})

    prom_unhashed = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash=H1,
        m1e_profile_set_hash=H2,
        decision_handoff_hash=H3,
        audit_handoff_hash=H4,
        input_bundle_hash=H1,
        provenance_proof_hash=H3,
        admission_hash=H0,
    )
    prom_hash = promotion_evaluation_admission_hash(prom_unhashed)
    prom_admission = prom_unhashed.model_copy(update={"admission_hash": prom_hash})

    # JSON round trip through union adapter
    exp_json = adapter.dump_json(exp_admission)
    loaded_exp = adapter.validate_json(exp_json)
    assert isinstance(loaded_exp, ExploratoryEvaluationAdmissionV1)
    assert loaded_exp == exp_admission

    prom_json = adapter.dump_json(prom_admission)
    loaded_prom = adapter.validate_json(prom_json)
    assert isinstance(loaded_prom, PromotionEvaluationAdmissionV1)
    assert loaded_prom == prom_admission


def test_canonical_alpaca_limitation_constants() -> None:
    constants = (
        ALPACA_LIMITATION_TRUNCATED_CA,
        ALPACA_LIMITATION_UNVERSIONED_BARS,
        ALPACA_LIMITATION_ABSENT_HALTS,
        ALPACA_LIMITATION_BOUNDED_COHORT,
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
        ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    )
    assert len(constants) == 6
    assert len(set(constants)) == 6
    for c in constants:
        assert isinstance(c, str)
        assert len(c) > 0


def test_exploratory_admission_blank_limitation_rejected() -> None:
    limitations = ("   ",)
    unhashed = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H1,
        acknowledged_limitations=limitations,
        admission_hash=H0,
    )
    h = exploratory_evaluation_admission_hash(unhashed)
    with pytest.raises(ValidationError):
        ExploratoryEvaluationAdmissionV1(
            schema_version="1",
            lane="exploratory",
            input_bundle_hash=H1,
            acknowledged_limitations=limitations,
            admission_hash=h,
        )


def test_no_promotion_conversion_or_mutability_seam() -> None:
    for forbidden in (
        "upgrade_exploratory_to_promotion",
        "convert_to_promotion",
        "promote_to_promotion",
        "upgrade_admission_lane",
    ):
        assert not hasattr(lanes_module, forbidden)
    for model in (ExploratoryEvaluationAdmissionV1, PromotionEvaluationAdmissionV1):
        assert "is_promotable" not in model.model_fields
        lane_annotation = model.model_fields["lane"].annotation
        assert get_origin(lane_annotation) is Literal
        assert len(get_args(lane_annotation)) == 1
        assert model.model_config.get("frozen") is True
